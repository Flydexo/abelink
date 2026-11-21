"""Deterministic 4-step Search Agent orchestrating parsing, hybrid + web retrieval, JIT enrichment, pathfinding & drafting."""

from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

import numpy as np

from app.db.repository import AbstractAlumniRepository, ProfileRecord, SearchCandidate
from app.schemas.search import (
    ActionPlanRequest,
    ActionPlanResponse,
    ActionStep,
    AlumniSolution,
    ConnectionPath,
    ParsedQuery,
    ScoreBreakdown,
    SSEEvent,
)
from app.services.enrichment import EnrichmentService
from app.services.graph_engine import (
    GraphEngine,
    normalize_company,
    strip_accents,
)
from app.services.llm import (
    LLMServiceProtocol,
    VertexLLMService,
    compute_verified_common_points,
    deterministic_text_embedding,
)

EventCallback = Callable[[SSEEvent], Awaitable[None]]

_RELEVANCE_STOPWORDS = {
    "je", "tu", "il", "elle", "nous", "vous", "un", "une", "des", "le", "la", "les",
    "du", "de", "d", "et", "ou", "dans", "en", "sur", "avec", "pour", "qui", "que",
    "cherche", "veux", "voudrais", "trouver", "contacter", "echanger", "parler",
    "alumni", "ancien", "ancienne", "etudiant", "etudiante", "quelqu", "boite",
    "entreprise", "travaille", "stage", "cesure", "fait", "aime", "membre",
}


def _cosine(a: Optional[list[float]], b: Optional[list[float]]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 0.0:
        return 0.0
    return max(0.0, min(1.0, float(np.dot(va, vb) / denom)))


def _compute_profile_relevance(
    candidate: SearchCandidate,
    det_query_vec: list[float],
    vertex_query_vec: list[float],
    parsed: ParsedQuery,
    *,
    raw_query: str = "",
    discovered_ids: Optional[set[str]] = None,
) -> float:
    profile = candidate.profile
    qvec = vertex_query_vec if profile.embedding_space == "vertex" else det_query_vec
    raw_sem = _cosine(qvec, profile.embedding) if profile.embedding else candidate.semantic_score
    if profile.embedding_space == "vertex":
        # Rescale gemini-embedding-2 cosine cone [0.68, 0.92] onto [0.0, 1.0]
        sem = max(0.0, min(1.0, (raw_sem - 0.68) / 0.24))
    else:
        sem = raw_sem

    structured_bonus = 0.0
    searchable = strip_accents(profile.searchable_text()).lower()
    has_explicit_criteria = bool(
        parsed.target_sector or parsed.target_companies or parsed.target_roles or parsed.worked_with
    )
    matched_explicit = False

    if parsed.target_sector:
        sector_norm = strip_accents(parsed.target_sector).lower()
        p_sector = strip_accents(profile.sector or "").lower()
        tokens = [t for t in sector_norm.replace("/", " ").split() if len(t) > 2]
        if sector_norm in p_sector or (tokens and any(t in p_sector for t in tokens)):
            structured_bonus += 0.25
            matched_explicit = True
        elif tokens and any(t in searchable for t in tokens):
            structured_bonus += 0.14
            matched_explicit = True

    if parsed.target_companies:
        p_comp = normalize_company(profile.current_company)
        exp_comps = {normalize_company(e.get("company")) for e in profile.experiences}
        for comp in parsed.target_companies:
            nc = normalize_company(comp)
            if nc and (nc == p_comp or nc in p_comp or nc in exp_comps or nc in searchable):
                structured_bonus += 0.40
                matched_explicit = True
                break

    if parsed.target_roles:
        p_role = strip_accents(profile.current_role or "").lower()
        for role in parsed.target_roles:
            nr = strip_accents(role).lower()
            if nr and (nr in p_role or nr in searchable):
                structured_bonus += 0.30
                matched_explicit = True
                break

    if parsed.worked_with:
        ww = strip_accents(parsed.worked_with).lower()
        if ww in searchable:
            structured_bonus += 0.25
            matched_explicit = True

    query_tokens = [
        tok
        for tok in re.findall(r"[a-z0-9]{3,}", strip_accents(raw_query).lower())
        if tok not in _RELEVANCE_STOPWORDS
    ]
    if query_tokens:
        kw_hits = sum(1 for tok in dict.fromkeys(query_tokens) if tok in searchable)
        structured_bonus += min(0.24, 0.08 * kw_hits)

    if discovered_ids and profile.id in discovered_ids and (profile.current_company or profile.sector or profile.bio):
        structured_bonus += 0.12

    relevance = 0.50 * sem + min(0.50, structured_bonus)
    if has_explicit_criteria and not matched_explicit:
        relevance = min(relevance, 0.20)
    return round(max(0.0, min(1.0, relevance)), 4)


def _compute_icebreakers_and_score(
    student: ProfileRecord,
    target: ProfileRecord,
    first_hop: Optional[ProfileRecord],
    parsed: ParsedQuery,
) -> tuple[list[str], float]:
    verified_target = compute_verified_common_points(student, target)
    verified_first = compute_verified_common_points(student, first_hop) if first_hop else []

    icebreakers: list[str] = []
    for item in verified_first + verified_target:
        if item not in icebreakers:
            icebreakers.append(item)

    target_tokens = strip_accents(
        " ".join(target.passions + target.associations + [target.bio or ""])
    ).lower()
    requested_hits = 0
    for req_ice in parsed.icebreakers:
        norm_req = strip_accents(req_ice).lower().strip()
        if norm_req and norm_req in target_tokens:
            requested_hits += 1
            label = f"Point d'accroche vérifié : {req_ice}"
            if label not in icebreakers:
                icebreakers.append(label)

    specific_count = sum(1 for item in icebreakers if item != "Réseau CentraleSupélec") + requested_hits
    generic_bonus = 0.2 if icebreakers else 0.0
    score = min(1.0, generic_bonus + specific_count / 3.0)
    return icebreakers, round(score, 4)


def _build_action_plan(
    target: ProfileRecord,
    primary_path: Optional[ConnectionPath],
    icebreakers: list[str],
) -> list[ActionStep]:
    if not primary_path or not primary_path.hops:
        return [
            ActionStep(
                when="Aujourd’hui",
                text=f"Préparez un message personnalisé pour {target.full_name} ({target.current_company or 'alumni CentraleSupélec'}).",
            ),
            ActionStep(
                when="Sous 3 jours",
                text="Partagez votre contexte et une question précise sur son parcours.",
            ),
            ActionStep(
                when="Sous 7 jours",
                text="Proposez un court échange de 15 à 20 minutes en visio.",
            ),
        ]

    hops = primary_path.hops
    first = hops[0]
    hint = icebreakers[0] if icebreakers else first.reason

    if len(hops) == 1:
        return [
            ActionStep(
                when="Aujourd’hui",
                text=f"Écrivez directement à {target.full_name} en vous appuyant sur votre lien ({first.reason}).",
            ),
            ActionStep(
                when="Sous 3 jours",
                text=f"Relancez si besoin en mentionnant votre point commun ({hint}).",
            ),
            ActionStep(
                when="Sous 7 jours",
                text=f"Proposez 20 minutes d’échange à {target.full_name} avec deux questions préparées.",
            ),
        ]

    second = hops[1]
    if len(hops) == 2:
        return [
            ActionStep(
                when="Aujourd’hui",
                text=f"Écrivez à {first.to_name} ({first.reason}) pour solliciter une mise en relation.",
            ),
            ActionStep(
                when="Sous 3 jours",
                text=f"{first.to_name} vous introduit auprès de {target.full_name} ({second.reason}).",
            ),
            ActionStep(
                when="Sous 7 jours",
                text=f"Proposez un créneau de 20 minutes à {target.full_name} pour préparer votre projet.",
            ),
        ]

    return [
        ActionStep(
            when="Aujourd’hui",
            text=f"Écrivez à {first.to_name} ({first.reason}) : c’est votre point d’entrée le plus solide.",
        ),
        ActionStep(
            when="Sous 3 jours",
            text=f"Demandez-lui de vous présenter {second.to_name}, qui relie votre réseau à {hops[-1].to_name}.",
        ),
        ActionStep(
            when="Sous 7 jours",
            text=f"{hops[-1].from_name} vous introduit auprès de {target.full_name} : proposez 20 minutes d’échange.",
        ),
    ]


class SearchAgentService:
    """4-step deterministic pipeline: parse -> hybrid + web retrieve -> JIT enrich -> score, pathfind & draft."""

    def __init__(
        self,
        repository: AbstractAlumniRepository,
        llm_service: LLMServiceProtocol,
        enrichment_service: EnrichmentService,
        graph_engine: GraphEngine,
    ) -> None:
        self.repository = repository
        self.llm = llm_service
        self.enrichment = enrichment_service
        self.graph_engine = graph_engine

    @staticmethod
    def _should_run_web_discovery(candidates: list[SearchCandidate], parsed: ParsedQuery) -> bool:
        """Discover via Tavily when DB careers are sparse (e.g. LinkCS) or requested company is missing."""
        with_career = sum(1 for c in candidates[:8] if c.profile.current_company or c.profile.sector)
        if with_career < 2:
            return True
        if parsed.target_companies:
            requested = [normalize_company(c) for c in parsed.target_companies if normalize_company(c)]
            top_companies = {
                normalize_company(c.profile.current_company)
                for c in candidates[:10]
                if c.profile.current_company
            }
            if requested and not (set(requested) & top_companies):
                return True
        return False

    async def run_action_plan(
        self,
        student_id: str,
        request: ActionPlanRequest,
        *,
        event_callback: Optional[EventCallback] = None,
    ) -> ActionPlanResponse:
        async def emit(ev: SSEEvent) -> None:
            if event_callback is not None:
                await event_callback(ev)

        student = await self.repository.get_profile(student_id)
        if student is None:
            raise ValueError(f"Profil étudiant introuvable: {student_id}")

        # Step 1: Parse query with LLM (Structured Output + JSON fallback)
        parsed = await self.llm.parse_user_query(request.query)
        if request.filters:
            if request.filters.sector:
                parsed.target_sector = request.filters.sector
            if request.filters.companies:
                parsed.target_companies = request.filters.companies
            if request.filters.roles:
                parsed.target_roles = request.filters.roles
            if request.filters.worked_with:
                parsed.worked_with = request.filters.worked_with
            if request.filters.icebreakers:
                parsed.icebreakers = list(dict.fromkeys([*parsed.icebreakers, *request.filters.icebreakers]))

        await emit(
            SSEEvent(
                event="parsing",
                title="Analyse de la demande",
                status="done",
                detail=parsed.summary_label or f"{parsed.intent} · {parsed.target_sector or 'réseau alumni'}",
                data={"parsed_query": parsed.model_dump()},
            )
        )

        # Step 2: Hybrid SQL + pgvector pre-filter + optional Tavily Web Discovery for sparse DBs (LinkCS)
        det_query_vec = deterministic_text_embedding(request.query, dim=768)
        vertex_query_vec = (
            (await self.llm.embed_texts([request.query]))[0]
            if isinstance(self.llm, VertexLLMService)
            else det_query_vec
        )

        candidates = await self.repository.hybrid_search_alumni(
            det_query_vec,
            parsed,
            filters=request.filters,
            exclude_profile_id=student.id,
            limit=20,
            raw_query=request.query,
            vertex_query_embedding=vertex_query_vec,
        )

        discovered_ids: set[str] = set()
        if self.enrichment.is_web_enabled() and self._should_run_web_discovery(candidates, parsed):
            all_profiles = await self.repository.list_profiles()
            discovered = await self.enrichment.discover_candidates_via_web(
                parsed,
                request.query,
                all_profiles,
            )
            discovered_ids = {p.id for p in discovered if p.id != student.id}
            if discovered_ids:
                existing_map = {c.profile.id: c for c in candidates}
                prioritized: list[SearchCandidate] = []
                for prof in discovered:
                    if prof.id == student.id:
                        continue
                    prev = existing_map.get(prof.id)
                    prioritized.append(
                        SearchCandidate(
                            profile=prof,
                            hybrid_score=(prev.hybrid_score if prev else 0.75) + 0.5,
                            semantic_score=prev.semantic_score if prev else 0.5,
                        )
                    )
                for c in candidates:
                    if c.profile.id not in discovered_ids:
                        prioritized.append(c)
                candidates = prioritized[:20]

        companies_matched = list(
            dict.fromkeys(
                c.profile.current_company
                for c in candidates
                if c.profile.current_company
            )
        )[:6]

        await emit(
            SSEEvent(
                event="hybrid_search",
                title="Pré-filtre sémantique & SQL",
                status="done",
                detail=(
                    f"{len(candidates)} candidats retenus (dont {len(discovered_ids)} identifié(s) sur le web)"
                    if discovered_ids
                    else f"{len(candidates)} profils candidats présélectionnés"
                ),
                chips=companies_matched,
                data={"candidates_scanned": len(candidates), "web_discovered": len(discovered_ids)},
            )
        )

        # Step 3: Just-In-Time Web Enrichment on uncached profiles
        enriched_profiles = await self.enrichment.enrich_candidates(
            [c.profile for c in candidates],
            extra_terms=None,
            max_concurrency=3,
            max_profiles=6,
        )
        enriched_by_id = {p.id: p for p in enriched_profiles}
        for c in candidates:
            if c.profile.id in enriched_by_id:
                c.profile = enriched_by_id[c.profile.id]

        companies_matched = list(
            dict.fromkeys(
                c.profile.current_company
                for c in candidates
                if c.profile.current_company
            )
        )[:6]

        await emit(
            SSEEvent(
                event="enrichment",
                title="Enrichissement web Just-In-Time",
                status="done",
                detail=(
                    f"{len(enriched_profiles)} profil(s) enrichi(s) via Tavily & Gemma 4"
                    if enriched_profiles
                    else "Tous les candidats pertinents étaient déjà en cache"
                ),
                chips=companies_matched,
                data={"candidates_enriched": len(enriched_profiles)},
            )
        )

        # Step 4: Re-scoring + NetworkX Dijkstra pathfinding
        scored_rows: list[tuple[bool, float, ProfileRecord, Optional[ConnectionPath], list[ConnectionPath], ScoreBreakdown, list[str]]] = []
        for cand in candidates:
            target = cand.profile
            paths = self.graph_engine.find_connection_paths(
                student.id,
                target.id,
                max_hops=4,
                k_paths=3,
            )
            primary_path = paths[0] if paths else None
            alt_paths = paths[1:] if len(paths) > 1 else []

            first_hop_prof: Optional[ProfileRecord] = None
            if primary_path and primary_path.hops:
                first_hop_prof = await self.repository.get_profile(primary_path.hops[0].to_id)

            prof_rel = _compute_profile_relevance(
                cand,
                det_query_vec,
                vertex_query_vec,
                parsed,
                raw_query=request.query,
                discovered_ids=discovered_ids,
            )
            path_prob = primary_path.total_probability if primary_path else 0.0
            icebreakers, common_score = _compute_icebreakers_and_score(
                student,
                target,
                first_hop_prof,
                parsed,
            )
            total_score = round(0.50 * prof_rel + 0.35 * path_prob + 0.15 * common_score, 4)

            breakdown = ScoreBreakdown(
                profile_relevance=prof_rel,
                path_probability=round(path_prob, 4),
                common_points_score=common_score,
                total_score=total_score,
            )
            is_relevant = prof_rel >= 0.22
            scored_rows.append((is_relevant, total_score, target, primary_path, alt_paths, breakdown, icebreakers))

        scored_rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
        total_candidates = len(scored_rows)
        selected = scored_rows[request.offset : request.offset + request.limit]

        await emit(
            SSEEvent(
                event="pathfinding",
                title="Calcul du graphe probabiliste",
                status="done",
                detail=f"{len(selected)} plan(s) d'action optimal(aux) calculé(s)",
                data={"solutions_count": len(selected)},
            )
        )

        solutions: list[AlumniSolution] = []
        for _, _, target, primary_path, alt_paths, breakdown, icebreakers in selected:
            first_hop_profile = target
            if primary_path and primary_path.hops:
                resolved = await self.repository.get_profile(primary_path.hops[0].to_id)
                if resolved is not None:
                    first_hop_profile = resolved

            verified_for_first_hop = compute_verified_common_points(student, first_hop_profile)
            outreach = await self.llm.generate_outreach_message(
                student=student,
                first_hop=first_hop_profile,
                target=target,
                hops=primary_path.hops if primary_path else [],
                intent=parsed.intent,
                common_points=verified_for_first_hop,
            )
            action_plan = _build_action_plan(target, primary_path, icebreakers)

            solutions.append(
                AlumniSolution(
                    target=target.to_profile_summary(),
                    primary_path=primary_path,
                    alternative_paths=alt_paths,
                    icebreakers=icebreakers,
                    action_plan=action_plan,
                    outreach_message=outreach,
                    first_hop=first_hop_profile.to_profile_summary(),
                    score_breakdown=breakdown,
                )
            )

        explicit_criteria = [
            *parsed.target_companies,
            *parsed.target_roles,
            *([parsed.target_sector] if parsed.target_sector else []),
        ]
        has_strong_match = any(s.score_breakdown.profile_relevance >= 0.35 for s in solutions)

        if explicit_criteria and not has_strong_match and solutions:
            criteria_str = " / ".join(explicit_criteria)
            summary = (
                f"Aucun match exact trouvé pour « {criteria_str} » dans l'extrait analysé ; "
                "voici les profils les plus proches dans votre réseau :"
            )
        elif solutions and solutions[0].primary_path:
            best = solutions[0]
            summary = (
                f"J’ai trouvé {len(solutions)} solution(s). La plus directe passe par "
                f"{best.primary_path.hop_count} lien(s) jusqu’à {best.target.full_name} "
                f"({best.primary_path.total_probability:.0%})."
            )
        elif solutions:
            summary = f"J’ai identifié {len(solutions)} profil(s) alumni pertinents, sans chemin indirect détecté pour l’instant."
        else:
            summary = "Aucun alumni correspondant trouvé dans la base actuelle."

        response = ActionPlanResponse(
            query=request.query,
            parsed_query=parsed,
            student_id=student.id,
            candidates_scanned=len(candidates),
            candidates_enriched=len(enriched_profiles),
            companies_matched=companies_matched,
            summary=summary,
            solutions=solutions,
            offset=request.offset,
            limit=request.limit,
            total_candidates=total_candidates,
        )

        await emit(
            SSEEvent(
                event="final_result",
                title="Plan d'action prêt",
                status="done",
                detail=summary,
                data={"response": response.model_dump(mode="json")},
            )
        )
        return response

    async def draft_custom_outreach(
        self,
        student_id: str,
        first_hop_id: str,
        target_id: str,
        context: str = "",
    ) -> dict[str, str]:
        student = await self.repository.get_profile(student_id)
        first_hop = await self.repository.get_profile(first_hop_id)
        target = await self.repository.get_profile(target_id)
        if not student or not first_hop or not target:
            raise ValueError("Impossible de trouver l'étudiant, le premier maillon ou la cible.")

        paths = self.graph_engine.find_connection_paths(student.id, target.id, max_hops=4, k_paths=3)
        chosen_hops = next(
            (p.hops for p in paths if p.hops and p.hops[0].to_id == first_hop.id),
            paths[0].hops if paths else [],
        )
        common_points = compute_verified_common_points(student, first_hop)
        message = await self.llm.generate_outreach_message(
            student=student,
            first_hop=first_hop,
            target=target,
            hops=chosen_hops,
            intent=context or "échange et conseil carrière",
            common_points=common_points,
            extra_context=context or None,
        )
        return {
            "first_hop_id": first_hop.id,
            "first_hop_name": first_hop.full_name,
            "target_id": target.id,
            "target_name": target.full_name,
            "verified_common_points": ", ".join(common_points),
            "message": message,
        }
