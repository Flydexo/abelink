"""Conversational iterative tool-calling Agent Chat service for Abelink."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from google.genai import types
from pydantic import BaseModel, Field

from app.db.repository import AbstractAlumniRepository, ProfileRecord, SearchCandidate
from app.schemas.chat import (
    ChatMessage,
    ChatPersonResult,
    ChatResponse,
    MutualContact,
    ToolCallTrace,
)
from app.schemas.search import ParsedQuery, SearchFilters
from app.services.enrichment import EnrichmentService
from app.services.graph_engine import GraphEngine, normalize_company, strip_accents
from app.services.llm import (
    LLMServiceProtocol,
    VertexLLMService,
    deterministic_text_embedding,
    extract_json_fallback,
)
from app.services.search_agent import SearchAgentService, _compute_profile_relevance, _cosine

ChatEventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]

MAX_AGENT_STEPS = 6

_GREETING_TOKENS = {
    "bonjour", "bonsoir", "salut", "hello", "hey", "coucou", "merci",
    "ok", "daccord", "ca", "va", "aide", "moi", "stp", "svp",
}

_FRIEND_STOPWORDS = {
    "des", "de", "du", "d", "qui", "que", "pour", "dans", "sur", "chez",
    "avec", "un", "une", "le", "la", "les", "et", "ou", "travaillant",
    "travaille", "bossant", "bosse", "faisant", "fait",
}

_FRIEND_PATTERN = re.compile(
    r"(?:parmi\s+les\s+(?:amis|connexions|contacts|relations)\s+d[e']\s*"
    r"|dans\s+les\s+(?:amis|connexions|contacts|relations)\s+d[e']\s*"
    r"|dans\s+le\s+r[eé]seau\s+d[e']\s*"
    r"|(?:amis|connexions|contacts)\s+d[e']\s*"
    r"|r[eé]seau\s+d[e']\s*)"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-']*(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-']*){0,2})",
    flags=re.IGNORECASE,
)

_COMMAND_FILLER_TOKENS = {
    "trouve", "trouver", "cherche", "chercher", "montre", "montrer",
    "regarde", "regarder", "liste", "lister", "voir", "vois", "essai", "essaye",
    "moi", "nous", "les", "des", "une", "un", "dans", "parmi", "sur", "pour",
    "stp", "svp", "merci", "quelqu", "gens", "personnes", "profils", "alumni",
}

_SEARCH_FOR_OTHERS_HINTS = (
    "trouve", "cherche", "autres", "similaire", "similaires", "comme",
    "liste", "quelqu'un", "quelqu un", "alumni dans", "qui travaille chez",
    "qui bosse chez", "profils dans", "contacts chez",
)

_PROFILE_QA_HINTS = (
    "parcours", "experience", "experiences", "bio", "profil", "detail", "details",
    "detaille", "association", "associations", "asso", "assos", "passion", "passions",
    "etude", "etudes", "formation", "diplome", "localisation", "ville", "habite",
    "travaille", "fait", "parle", "raconte", "dis-m'en", "dis m'en", "infos",
    "information", "informations", "qui est", "c'est qui", "presente",
)


class _NativeToolsUnsupported(Exception):
    """Internal signal when the Vertex Gemma endpoint rejects native function declarations."""


class _ReactTurn(BaseModel):
    thought: str = ""
    intro: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str = ""
    selected_people: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class _TurnState:
    student: ProfileRecord
    all_profiles: list[ProfileRecord]
    profile_by_id: dict[str, ProfileRecord]
    candidates_by_id: dict[str, SearchCandidate] = field(default_factory=dict)
    relevance_by_id: dict[str, float] = field(default_factory=dict)
    discovered_ids: set[str] = field(default_factory=set)
    enriched_ids: set[str] = field(default_factory=set)
    mutuals_by_id: dict[str, tuple[list[MutualContact], Optional[int]]] = field(default_factory=dict)
    friend_profile: Optional[ProfileRecord] = None
    friend_not_found_name: Optional[str] = None
    allowed_ids: Optional[set[str]] = None
    last_query: str = ""
    last_parsed: Optional[ParsedQuery] = None
    det_query_vec: Optional[list[float]] = None
    vertex_query_vec: Optional[list[float]] = None
    total_candidates: int = 0
    drafted_message: Optional[str] = None
    draft_verified_common_points: str = ""
    draft_target: Optional[ProfileRecord] = None
    draft_first_hop: Optional[ProfileRecord] = None
    inspected_profile_ids: list[str] = field(default_factory=list)
    tools_used: list[ToolCallTrace] = field(default_factory=list)
    tool_seq: int = 0
    intro_emitted: bool = False
    intro_text: str = ""


def _clean_role_or_company(value: Optional[str]) -> Optional[str]:
    """Filter out malformed sentence fragments, URLs, or noisy extraction artifacts."""
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n,;:-")
    if not cleaned:
        return None
    lowered = strip_accents(cleaned).lower()
    if "http://" in lowered or "https://" in lowered or "linkedin.com" in lowered:
        return None
    if len(cleaned) > 70:
        return None
    words = cleaned.split()
    if len(words) > 9:
        return None
    if re.search(r"[.!?]\s+\w", cleaned):
        return None
    narrative_prefixes = (
        "est ", "a ", "il ", "elle ", "diplome ", "diplomee ", "ancien ", "ancienne ",
        "actuellement ", "travaille ", "passionne ", "membre ",
    )
    if len(words) >= 4 and lowered.startswith(narrative_prefixes):
        return None
    if cleaned.endswith(".") and len(words) >= 4:
        return None
    return cleaned.rstrip(".") if not cleaned.endswith("Inc.") else cleaned


def _format_role_company(profile: ProfileRecord) -> str:
    role = _clean_role_or_company(profile.current_role)
    company = _clean_role_or_company(profile.current_company)

    if not role and not company and profile.experiences:
        for exp in profile.experiences:
            exp_role = _clean_role_or_company(exp.get("role"))
            exp_comp = _clean_role_or_company(exp.get("company"))
            if exp_role or exp_comp:
                role = role or exp_role
                company = company or exp_comp
                break

    if role and company:
        return f"{role} chez {company}"
    if role:
        return role
    if company:
        return company
    if profile.promo_year:
        return f"Alumni · Promo {profile.promo_year}"
    return "Alumni CentraleSupélec"


def _is_enriched_profile(profile: ProfileRecord) -> bool:
    return bool(
        profile.last_enriched_at is not None
        or profile.has_imported_linkedin
        or _clean_role_or_company(profile.current_company)
        or profile.sector
        or (profile.bio and profile.bio.strip())
        or profile.experiences
    )


def _has_substantive_terms(text: str) -> bool:
    tokens = [
        tok
        for tok in re.findall(r"[a-z0-9]{2,}", strip_accents(text).lower())
        if tok not in _COMMAND_FILLER_TOKENS and tok not in _GREETING_TOKENS
    ]
    return len(tokens) >= 1


def _clean_friend_capture(raw_capture: str) -> str:
    tokens = re.split(r"\s+", raw_capture.strip(" ,.;:?!"))
    kept: list[str] = []
    for tok in tokens:
        if strip_accents(tok).lower() in _FRIEND_STOPWORDS:
            break
        kept.append(tok)
    return " ".join(kept).strip()


def _extract_friend_filter_from_text(text: str) -> tuple[Optional[str], str]:
    """Return (friend_name_or_none, query_without_friend_clause)."""
    match = _FRIEND_PATTERN.search(text)
    if not match:
        return None, text
    cleaned_name = _clean_friend_capture(match.group(1))
    if not cleaned_name:
        return None, text
    full_clause = match.group(0)
    raw_cap = match.group(1)
    idx_in_cap = raw_cap.lower().find(cleaned_name.lower())
    clause_end = match.start() + (full_clause.lower().find(raw_cap.lower()) + idx_in_cap + len(cleaned_name))
    remainder = f"{text[:match.start()]} {text[clause_end:]}".strip()
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,.;:?!-")
    return cleaned_name, remainder


def _match_profile_by_name(
    name_query: Optional[str],
    profiles: list[ProfileRecord],
    *,
    exclude_id: Optional[str] = None,
) -> Optional[ProfileRecord]:
    if not name_query:
        return None
    needle = strip_accents(name_query).lower().strip()
    if not needle:
        return None

    pool = [p for p in profiles if p.id != exclude_id]
    for p in pool:
        if strip_accents(p.full_name).lower().strip() == needle:
            return p
    for p in pool:
        norm_full = strip_accents(p.full_name).lower().strip()
        if norm_full.startswith(needle) or re.search(rf"\b{re.escape(needle)}\b", norm_full):
            return p
    first_token = needle.split()[0]
    for p in pool:
        parts = strip_accents(p.full_name).lower().split()
        if parts and parts[0] == first_token:
            return p
    return None


def _find_mentioned_profiles(
    text: str,
    profiles: list[ProfileRecord],
    *,
    exclude_id: Optional[str] = None,
) -> list[ProfileRecord]:
    """Find profiles mentioned by full name or unique first name in text, ordered by position."""
    norm_text = strip_accents(text).lower()
    hits: list[tuple[int, int, ProfileRecord]] = []

    first_name_counts: dict[str, int] = {}
    for p in profiles:
        if p.id == exclude_id:
            continue
        parts = strip_accents(p.full_name).lower().split()
        if parts:
            first_name_counts[parts[0]] = first_name_counts.get(parts[0], 0) + 1

    for p in profiles:
        if p.id == exclude_id:
            continue
        norm_full = strip_accents(p.full_name).lower().strip()
        m_full = re.search(rf"\b{re.escape(norm_full)}\b", norm_text)
        if m_full:
            hits.append((m_full.start(), -len(norm_full), p))
            continue
        parts = norm_full.split()
        if parts and len(parts[0]) >= 3 and first_name_counts.get(parts[0], 0) == 1:
            m_first = re.search(rf"\b{re.escape(parts[0])}\b", norm_text)
            if m_first:
                hits.append((m_first.start(), -len(parts[0]), p))

    hits.sort(key=lambda item: (item[0], item[1]))
    deduped: list[ProfileRecord] = []
    seen: set[str] = set()
    for _, _, prof in hits:
        if prof.id not in seen:
            seen.add(prof.id)
            deduped.append(prof)
    return deduped


def _build_deterministic_thinking(
    profile: ProfileRecord,
    parsed: Optional[ParsedQuery],
    relevance: float,
    explicit_criteria: list[str],
) -> str:
    sentences: list[str] = []

    role = _clean_role_or_company(profile.current_role)
    company = _clean_role_or_company(profile.current_company)
    if role and company:
        role_part = f"Actuellement {role} chez {company}"
    elif company:
        role_part = f"Travaille actuellement chez {company}"
    elif role:
        role_part = f"Exerce comme {role}"
    elif profile.promo_year:
        role_part = f"Alumni CentraleSupélec (promo {profile.promo_year})"
    else:
        role_part = "Alumni CentraleSupélec"

    if profile.sector:
        role_part += f" (secteur {profile.sector})"
    sentences.append(role_part + ".")

    past_company_match: Optional[str] = None
    if parsed and parsed.target_companies:
        cur_comp = normalize_company(company or profile.current_company)
        for req_comp in parsed.target_companies:
            req_norm = normalize_company(req_comp)
            if req_norm and req_norm != cur_comp and req_norm not in cur_comp:
                for exp in profile.experiences:
                    if req_norm in normalize_company(exp.get("company")):
                        past_company_match = exp.get("company") or req_comp
                        break

    if past_company_match:
        sentences.append(
            f"A précédemment travaillé chez {past_company_match}, même s'il ou elle n'y est plus en poste aujourd'hui."
        )
    elif explicit_criteria and relevance < 0.35:
        sentences.append(
            "Profil adjacent : pas de correspondance directe avec tous les critères demandés, mais son parcours peut apporter un éclairage connexe."
        )
    elif profile.bio and profile.bio.strip():
        bio_snippet = profile.bio.strip().rstrip(".")
        if len(bio_snippet) > 130:
            bio_snippet = bio_snippet[:127].rstrip() + "…"
        sentences.append(f"{bio_snippet}.")

    extras: list[str] = []
    if profile.associations:
        extras.append(f"associations ({', '.join(profile.associations[:2])})")
    if profile.passions:
        extras.append(f"centres d'intérêt ({', '.join(profile.passions[:2])})")
    if extras and len(sentences) < 3:
        sentences.append(f"Engagements et repères : {' ; '.join(extras)}.")

    return " ".join(sentences[:3])


def _build_profile_qa_prose(profiles: list[ProfileRecord]) -> str:
    """Synthesize grounded natural French prose from inspected profile details."""
    blocks: list[str] = []
    for p in profiles:
        parts: list[str] = []
        headline = _format_role_company(p)
        promo_txt = f" (promo {p.promo_year})" if p.promo_year else ""
        loc_txt = f", basé(e) à {p.location}" if p.location else ""
        parts.append(f"**{p.full_name}**{promo_txt} est actuellement {headline}{loc_txt}.")

        if p.sector:
            parts.append(f"Secteur principal : {p.sector}.")
        if p.bio and p.bio.strip():
            parts.append(p.bio.strip().rstrip(".") + ".")
        if p.experiences:
            exp_items: list[str] = []
            for exp in p.experiences[:4]:
                r = exp.get("role") or "Poste"
                c = exp.get("company") or ""
                period = exp.get("period") or (
                    f"{exp.get('start_date', '')} - {exp.get('end_date', '')}".strip(" -")
                )
                label = f"{r} chez {c}".strip() if c else r
                if period:
                    label += f" ({period})"
                exp_items.append(label)
            if exp_items:
                parts.append(f"Expériences notables : {', '.join(exp_items)}.")
        if p.associations:
            parts.append(f"Associations à CentraleSupélec : {', '.join(p.associations)}.")
        if p.passions:
            parts.append(f"Centres d'intérêt : {', '.join(p.passions)}.")
        if p.linkedin_url:
            parts.append(f"Profil LinkedIn : {p.linkedin_url}")
        blocks.append(" ".join(parts))
    return "\n\n".join(blocks)


def _build_vertex_tools() -> list[types.Tool]:
    """Declare the 6 Abelink agent tools for Vertex AI Gemini/Gemma native function calling."""
    declarations = [
        types.FunctionDeclaration(
            name="search_alumni",
            description=(
                "Recherche hybride (sémantique + mots-clés) dans l'annuaire alumni CentraleSupélec. "
                "Supporte un filtre optionnel par secteur, entreprise, poste ou cercle d'amis (1-2 sauts)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(type=types.Type.STRING, description="Requête de recherche en français ou mots-clés."),
                    "sector": types.Schema(type=types.Type.STRING, description="Secteur cible optionnel."),
                    "company": types.Schema(type=types.Type.STRING, description="Entreprise cible optionnelle."),
                    "role": types.Schema(type=types.Type.STRING, description="Poste ou rôle cible optionnel."),
                    "friend_name": types.Schema(
                        type=types.Type.STRING,
                        description="Prénom ou nom d'un contact pour limiter la recherche à ses connexions (1-2 sauts).",
                    ),
                    "limit": types.Schema(type=types.Type.INTEGER, description="Nombre max de candidats retournés (défaut 10)."),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="web_search_alumni",
            description=(
                "Découverte web/LinkedIn ciblée pour identifier des alumni CentraleSupélec correspondants "
                "lorsque les résultats en base sont incomplets ou manquent une entreprise demandée."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "queries": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description="1 à 3 requêtes ciblées pour la découverte web.",
                    ),
                },
                required=["queries"],
            ),
        ),
        types.FunctionDeclaration(
            name="enrich_alumni_profiles",
            description=(
                "Enrichit immédiatement des profils spécifiques (needs_enrichment=true) via le web/LinkedIn, "
                "met à jour leur bio, expériences, associations et recalcule leurs embeddings."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "profile_ids": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description="Liste des IDs de profils à enrichir.",
                    ),
                },
                required=["profile_ids"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_profile_details",
            description=(
                "Récupère la fiche complète d'un alumni (bio, expériences, formation, localisation, "
                "associations, passions) pour répondre à des questions précises en suivi de conversation."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "profile_id": types.Schema(type=types.Type.STRING, description="ID (ou nom) du profil à inspecter."),
                },
                required=["profile_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="find_mutual_connections",
            description=(
                "Identifie les contacts communs et chemins de mise en relation pour une liste d'alumni cibles."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "target_ids": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description="Liste des IDs des alumni cibles.",
                    ),
                },
                required=["target_ids"],
            ),
        ),
        types.FunctionDeclaration(
            name="draft_intro_message",
            description=(
                "Rédige un message de prise de contact anti-hallucination adressé au contact intermédiaire "
                "(ou directement à la cible si first_hop_id == target_id)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "first_hop_id": types.Schema(type=types.Type.STRING, description="ID du contact à qui écrire."),
                    "target_id": types.Schema(type=types.Type.STRING, description="ID de l'alumni cible final."),
                    "context": types.Schema(type=types.Type.STRING, description="Objectif ou contexte du message."),
                },
                required=["first_hop_id", "target_id"],
            ),
        ),
    ]
    return [types.Tool(function_declarations=declarations)]


def _build_agent_system_prompt(student: ProfileRecord) -> str:
    return (
        "Tu es l'agent conversationnel réseau d'Abelink pour les étudiants de CentraleSupélec.\n"
        f"Étudiant connecté : {student.full_name} (id={student.id}, promo {student.promo_year or 'N/A'}, "
        f"associations : {', '.join(student.associations) or 'aucune'}).\n\n"
        "Outils disponibles :\n"
        "1. search_alumni(query, sector='', company='', role='', friend_name='', limit=10)\n"
        "2. web_search_alumni(queries=[...])\n"
        "3. enrich_alumni_profiles(profile_ids=[...])\n"
        "4. get_profile_details(profile_id='...')\n"
        "5. find_mutual_connections(target_ids=[...])\n"
        "6. draft_intro_message(first_hop_id='...', target_id='...', context='')\n\n"
        "Stratégie itérative (max 6 étapes) :\n"
        "- Pour une salutation simple ou demande trop vague : réponds directement en français en demandant des précisions (sans appeler d'outil).\n"
        "- Pour une recherche d'alumni : appelle search_alumni en premier. Si les résultats manquent l'entreprise ou sont pauvres, appelle web_search_alumni. "
        "Si des candidats pertinents ont needs_enrichment=true, appelle enrich_alumni_profiles. "
        "Avant de conclure une recherche de profils, appelle TOUJOURS find_mutual_connections sur les IDs retenus.\n"
        "- Pour une question de suivi sur un profil précis (bio, parcours, assos, passions, localisation) : appelle get_profile_details et réponds en prose naturelle.\n"
        "- Pour rédiger un message d'introduction : identifie les IDs (via search_alumni/historique si besoin), appelle draft_intro_message.\n"
        "- Règle stricte d'honnêteté : ne cite JAMAIS de faits, entreprises, associations ou passions absents des observations d'outils."
    )


class ChatAgentService:
    """Conversational Happenstance-style Agent orchestrating iterative tools, mutuals, and grounded rationales."""

    def __init__(
        self,
        repository: AbstractAlumniRepository,
        llm_service: LLMServiceProtocol,
        enrichment_service: EnrichmentService,
        graph_engine: GraphEngine,
        search_agent: SearchAgentService,
    ) -> None:
        self.repository = repository
        self.llm = llm_service
        self.enrichment = enrichment_service
        self.graph_engine = graph_engine
        self.search_agent = search_agent

    # ------------------------------------------------------------------
    # Tool implementations (the 6 exposed agent tools)
    # ------------------------------------------------------------------

    async def _tool_search_alumni(
        self,
        args: dict[str, Any],
        state: _TurnState,
    ) -> tuple[dict[str, Any], str, str, int, str]:
        query = str(args.get("query") or "").strip()
        sector = str(args.get("sector") or "").strip()
        company = str(args.get("company") or "").strip()
        role = str(args.get("role") or "").strip()
        friend_name = str(args.get("friend_name") or "").strip()
        raw_limit = args.get("limit", 10)
        try:
            limit_val = max(1, min(int(raw_limit), 20))
        except (TypeError, ValueError):
            limit_val = 10

        effective_query = query or " ".join(x for x in (company, role, sector) if x).strip() or "alumni"

        allowed_ids: Optional[set[str]] = None
        if friend_name:
            friend_prof = _match_profile_by_name(friend_name, state.all_profiles, exclude_id=state.student.id)
            if friend_prof is None:
                state.friend_not_found_name = friend_name
                obs = {
                    "status": "friend_not_found",
                    "friend_name": friend_name,
                    "count": 0,
                    "candidates": [],
                }
                return (
                    obs,
                    f"Recherche dans le réseau de {friend_name}",
                    f"Requête : {effective_query[:70]}",
                    0,
                    f"Aucun membre nommé « {friend_name} » trouvé",
                )
            state.friend_profile = friend_prof
            allowed_ids = self.graph_engine.get_neighborhood_ids(
                friend_prof.id,
                max_hops=2,
                exclude_ids={state.student.id},
            )
            state.allowed_ids = allowed_ids

        parsed = await self.llm.parse_user_query(effective_query)
        if sector:
            parsed.target_sector = sector
        if company and company not in parsed.target_companies:
            parsed.target_companies = [company, *parsed.target_companies]
        if role and role not in parsed.target_roles:
            parsed.target_roles = [role, *parsed.target_roles]

        search_filters = (
            SearchFilters(
                sector=sector or None,
                companies=[company] if company else [],
                roles=[role] if role else [],
            )
            if (sector or company or role)
            else None
        )

        det_vec = deterministic_text_embedding(effective_query, dim=768)
        vertex_vec = (
            (await self.llm.embed_texts([effective_query]))[0]
            if isinstance(self.llm, VertexLLMService)
            else det_vec
        )
        state.last_query = effective_query
        state.last_parsed = parsed
        state.det_query_vec = det_vec
        state.vertex_query_vec = vertex_vec

        candidates = await self.repository.hybrid_search_alumni(
            det_vec,
            parsed,
            filters=search_filters,
            exclude_profile_id=state.student.id,
            limit=50 if allowed_ids is not None else max(20, limit_val),
            raw_query=effective_query,
            vertex_query_embedding=vertex_vec,
        )

        if allowed_ids is not None:
            candidates = [c for c in candidates if c.profile.id in allowed_ids]
            existing_ids = {c.profile.id for c in candidates}
            for nid in allowed_ids:
                if nid in existing_ids:
                    continue
                prof = state.profile_by_id.get(nid)
                if prof is None or prof.is_student:
                    continue
                qvec = vertex_vec if prof.embedding_space == "vertex" else det_vec
                sem = _cosine(qvec, prof.embedding) if prof.embedding else 0.25
                candidates.append(SearchCandidate(profile=prof, hybrid_score=sem, semantic_score=sem))

        scored: list[tuple[bool, float, float, SearchCandidate]] = []
        for cand in candidates:
            rel = _compute_profile_relevance(
                cand,
                det_vec,
                vertex_vec,
                parsed,
                raw_query=effective_query,
                discovered_ids=state.discovered_ids,
            )
            bonus = self._current_match_bonus(cand.profile, parsed)
            scored.append((rel >= 0.22, rel + bonus, rel, cand))
            state.candidates_by_id[cand.profile.id] = cand
            state.relevance_by_id[cand.profile.id] = rel

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        state.total_candidates = max(state.total_candidates, len(scored))
        top_scored = scored[:limit_val]

        cand_obs = [
            {
                "id": cand.profile.id,
                "full_name": cand.profile.full_name,
                "current_role": cand.profile.current_role,
                "current_company": cand.profile.current_company,
                "sector": cand.profile.sector,
                "location": cand.profile.location,
                "promo_year": cand.profile.promo_year,
                "relevance": round(rel, 3),
                "needs_enrichment": self.enrichment.needs_enrichment(cand.profile),
                "has_linkedin": bool(cand.profile.linkedin_url),
                "bio_preview": (cand.profile.bio or "")[:140],
            }
            for _, _, rel, cand in top_scored
        ]
        obs = {
            "count": len(cand_obs),
            "total_scanned": len(scored),
            "friend_scope": state.friend_profile.full_name if state.friend_profile else None,
            "candidates": cand_obs,
        }

        label = (
            f"Recherche dans le réseau de {state.friend_profile.full_name}"
            if state.friend_profile
            else "Recherche hybride dans l'annuaire"
        )
        detail_parts = [x for x in (company, role, sector) if x]
        detail = " · ".join(detail_parts) if detail_parts else effective_query[:80]
        summary = f"{len(cand_obs)} candidat(s) trouvé(s)"
        return obs, label, detail, len(cand_obs), summary

    async def _tool_web_search_alumni(
        self,
        args: dict[str, Any],
        state: _TurnState,
    ) -> tuple[dict[str, Any], str, str, int, str]:
        raw_queries = args.get("queries") or []
        if isinstance(raw_queries, str):
            raw_queries = [raw_queries]
        queries = [str(q).strip() for q in raw_queries if str(q).strip()][:3]
        if not queries and state.last_query:
            queries = [state.last_query]

        detail = " · ".join(queries[:2])[:90]
        if not self.enrichment.is_web_enabled():
            return (
                {"status": "web_disabled", "count": 0, "discovered": []},
                "Découverte web LinkedIn",
                detail,
                0,
                "Recherche web désactivée",
            )

        discovered_map: dict[str, ProfileRecord] = {}
        for q_str in queries[:2]:
            p_q = (
                state.last_parsed
                if state.last_parsed and q_str == state.last_query
                else await self.llm.parse_user_query(q_str)
            )
            found = await self.enrichment.discover_candidates_via_web(p_q, q_str, state.all_profiles)
            for prof in found:
                if prof.id == state.student.id:
                    continue
                if state.allowed_ids is not None and prof.id not in state.allowed_ids:
                    continue
                discovered_map[prof.id] = prof

        discovered_list = list(discovered_map.values())
        for prof in discovered_list:
            state.discovered_ids.add(prof.id)
            prev = state.candidates_by_id.get(prof.id)
            cand = SearchCandidate(
                profile=prof,
                hybrid_score=(prev.hybrid_score if prev else 0.75) + 0.5,
                semantic_score=prev.semantic_score if prev else 0.5,
            )
            state.candidates_by_id[prof.id] = cand
            if state.det_query_vec is not None and state.vertex_query_vec is not None and state.last_parsed is not None:
                state.relevance_by_id[prof.id] = _compute_profile_relevance(
                    cand,
                    state.det_query_vec,
                    state.vertex_query_vec,
                    state.last_parsed,
                    raw_query=state.last_query,
                    discovered_ids=state.discovered_ids,
                )

        state.total_candidates = max(state.total_candidates, len(state.candidates_by_id))
        obs = {
            "count": len(discovered_list),
            "discovered": [
                {
                    "id": p.id,
                    "full_name": p.full_name,
                    "current_role": p.current_role,
                    "current_company": p.current_company,
                    "location": p.location,
                    "needs_enrichment": self.enrichment.needs_enrichment(p),
                    "has_linkedin": bool(p.linkedin_url),
                }
                for p in discovered_list
            ],
        }
        return (
            obs,
            "Découverte web LinkedIn",
            detail,
            len(discovered_list),
            f"{len(discovered_list)} profil(s) identifié(s) sur le web",
        )

    async def _tool_enrich_alumni_profiles(
        self,
        args: dict[str, Any],
        state: _TurnState,
    ) -> tuple[dict[str, Any], str, str, int, str]:
        raw_ids = args.get("profile_ids") or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        targets: list[ProfileRecord] = []
        for pid in raw_ids:
            prof = state.profile_by_id.get(str(pid)) or _match_profile_by_name(
                str(pid), state.all_profiles, exclude_id=state.student.id
            )
            if prof is not None and prof.id != state.student.id and prof not in targets:
                targets.append(prof)

        detail = f"Extraction web & embeddings ({min(len(targets), 6)} profil(s))"
        if not targets or not self.enrichment.is_web_enabled():
            return (
                {"count": 0, "enriched": []},
                "Enrichissement Just-In-Time des profils",
                detail,
                0,
                "Aucun profil à enrichir" if not targets else "Enrichissement web indisponible",
            )

        enriched = await self.enrichment.enrich_candidates(
            targets,
            extra_terms=None,
            max_concurrency=3,
            max_profiles=6,
        )
        for prof in enriched:
            state.profile_by_id[prof.id] = prof
            state.enriched_ids.add(prof.id)
            prev = state.candidates_by_id.get(prof.id)
            cand = SearchCandidate(
                profile=prof,
                hybrid_score=prev.hybrid_score if prev else 0.7,
                semantic_score=prev.semantic_score if prev else 0.5,
            )
            state.candidates_by_id[prof.id] = cand
            if state.det_query_vec is not None and state.vertex_query_vec is not None and state.last_parsed is not None:
                state.relevance_by_id[prof.id] = _compute_profile_relevance(
                    cand,
                    state.det_query_vec,
                    state.vertex_query_vec,
                    state.last_parsed,
                    raw_query=state.last_query,
                    discovered_ids=state.discovered_ids,
                )

        if enriched:
            state.all_profiles = list(state.profile_by_id.values())

        obs = {
            "count": len(enriched),
            "enriched": [
                {
                    "id": p.id,
                    "full_name": p.full_name,
                    "current_role": p.current_role,
                    "current_company": p.current_company,
                    "sector": p.sector,
                    "location": p.location,
                    "bio": p.bio,
                    "associations": p.associations,
                    "passions": p.passions,
                    "experiences_count": len(p.experiences),
                    "relevance": round(state.relevance_by_id.get(p.id, 0.0), 3),
                }
                for p in enriched
            ],
        }
        return (
            obs,
            "Enrichissement Just-In-Time des profils",
            detail,
            len(enriched),
            f"{len(enriched)} profil(s) enrichi(s) et ré-indexé(s)",
        )

    async def _tool_get_profile_details(
        self,
        args: dict[str, Any],
        state: _TurnState,
    ) -> tuple[dict[str, Any], str, str, int, str]:
        raw_id = str(args.get("profile_id") or "").strip()
        prof = state.profile_by_id.get(raw_id) or await self.repository.get_profile(raw_id)
        if prof is None:
            prof = _match_profile_by_name(raw_id, state.all_profiles, exclude_id=state.student.id)

        if prof is None:
            return (
                {"found": False, "profile_id": raw_id, "error": "Profil introuvable"},
                "Consultation du profil",
                raw_id,
                0,
                "Profil introuvable",
            )

        state.profile_by_id[prof.id] = prof
        if prof.id not in state.inspected_profile_ids:
            state.inspected_profile_ids.append(prof.id)

        obs = {
            "found": True,
            "id": prof.id,
            "full_name": prof.full_name,
            "promo_year": prof.promo_year,
            "current_role": prof.current_role,
            "current_company": prof.current_company,
            "sector": prof.sector,
            "location": prof.location,
            "linkedin_url": prof.linkedin_url,
            "photo_url": prof.photo_url,
            "bio": prof.bio,
            "experiences": prof.experiences,
            "education": prof.education,
            "associations": prof.associations,
            "passions": prof.passions,
            "enrichment_source": prof.enrichment_source,
            "has_imported_linkedin": prof.has_imported_linkedin,
            "needs_enrichment": self.enrichment.needs_enrichment(prof),
        }
        return (
            obs,
            f"Consultation du profil de {prof.full_name}",
            _format_role_company(prof),
            1,
            f"Fiche complète récupérée pour {prof.full_name}",
        )

    async def _tool_find_mutual_connections(
        self,
        args: dict[str, Any],
        state: _TurnState,
    ) -> tuple[dict[str, Any], str, str, int, str]:
        raw_ids = args.get("target_ids") or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]

        connections_obs: dict[str, Any] = {}
        total_links = 0
        analyzed = 0
        for tid in raw_ids:
            target = state.profile_by_id.get(str(tid)) or _match_profile_by_name(
                str(tid), state.all_profiles, exclude_id=state.student.id
            )
            if target is None or target.id == state.student.id:
                continue
            muts, hops = self._collect_mutuals_for_target(
                state.student.id, target, state.profile_by_id, state.friend_profile
            )
            state.mutuals_by_id[target.id] = (muts, hops)
            analyzed += 1
            total_links += len(muts)
            connections_obs[target.id] = {
                "full_name": target.full_name,
                "hop_count": hops,
                "mutuals": [
                    {
                        "id": m.id,
                        "full_name": m.full_name,
                        "short_meta": m.short_meta,
                        "reason": m.reason,
                        "probability": m.probability,
                    }
                    for m in muts
                ],
            }

        obs = {
            "targets_analyzed": analyzed,
            "total_mutual_links": total_links,
            "connections": connections_obs,
        }
        return (
            obs,
            "Identification des contacts communs",
            f"Analyse des chemins réseau pour {analyzed} profil(s)",
            total_links,
            f"{total_links} contact(s) commun(s) trouvé(s) sur {analyzed} profil(s)",
        )

    async def _tool_draft_intro_message(
        self,
        args: dict[str, Any],
        state: _TurnState,
    ) -> tuple[dict[str, Any], str, str, int, str]:
        raw_fh = str(args.get("first_hop_id") or "").strip()
        raw_tg = str(args.get("target_id") or "").strip()
        context = str(args.get("context") or "").strip()

        target = state.profile_by_id.get(raw_tg) or _match_profile_by_name(
            raw_tg, state.all_profiles, exclude_id=state.student.id
        )
        first_hop = state.profile_by_id.get(raw_fh) or _match_profile_by_name(
            raw_fh, state.all_profiles, exclude_id=state.student.id
        )

        if target is None and first_hop is not None:
            target = first_hop
            first_hop = None

        if target is None:
            return (
                {"status": "error", "error": "Cible introuvable dans l'annuaire."},
                "Rédaction d'introduction",
                raw_tg or raw_fh,
                0,
                "Cible introuvable",
            )

        if first_hop is None:
            paths = self.graph_engine.find_connection_paths(state.student.id, target.id, max_hops=4, k_paths=1)
            if paths and paths[0].hops:
                first_hop = state.profile_by_id.get(paths[0].hops[0].to_id) or target
            else:
                first_hop = target

        draft_res = await self.search_agent.draft_custom_outreach(
            student_id=state.student.id,
            first_hop_id=first_hop.id,
            target_id=target.id,
            context=context,
        )
        state.drafted_message = draft_res["message"]
        state.draft_verified_common_points = draft_res.get("verified_common_points", "")
        state.draft_target = target
        state.draft_first_hop = first_hop

        label = f"Rédaction d'introduction à {first_hop.full_name}"
        detail = f"Cible : {target.full_name}" if first_hop.id != target.id else "Contact direct"
        return (
            draft_res,
            label,
            detail,
            1,
            f"Message rédigé pour {first_hop.full_name}",
        )

    async def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        state: _TurnState,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> dict[str, Any]:
        """Dispatch a tool call, emit tool_start/tool_done SSE events, and record ToolCallTrace."""
        state.tool_seq += 1
        trace_id = f"tool-{name}-{state.tool_seq}"
        clean_args = dict(arguments or {})

        pre_label_map = {
            "search_alumni": (
                f"Recherche dans le réseau de {clean_args['friend_name']}"
                if clean_args.get("friend_name")
                else "Recherche hybride dans l'annuaire"
            ),
            "web_search_alumni": "Découverte web LinkedIn",
            "enrich_alumni_profiles": "Enrichissement Just-In-Time des profils",
            "get_profile_details": "Consultation du profil",
            "find_mutual_connections": "Identification des contacts communs",
            "draft_intro_message": "Rédaction d'introduction",
        }
        pre_label = pre_label_map.get(name, name)

        await emit(
            "tool_start",
            {
                "id": trace_id,
                "tool": name,
                "label": pre_label,
                "detail": "",
                "status": "running",
                "arguments": clean_args,
            },
        )

        t0 = time.monotonic()
        handlers = {
            "search_alumni": self._tool_search_alumni,
            "web_search_alumni": self._tool_web_search_alumni,
            "enrich_alumni_profiles": self._tool_enrich_alumni_profiles,
            "get_profile_details": self._tool_get_profile_details,
            "find_mutual_connections": self._tool_find_mutual_connections,
            "draft_intro_message": self._tool_draft_intro_message,
        }
        handler = handlers.get(name)
        if handler is None:
            obs = {"error": f"Outil inconnu: {name}"}
            label, detail, count, summary = name, "", 0, f"Outil inconnu: {name}"
        else:
            obs, label, detail, count, summary = await handler(clean_args, state)

        dur_ms = int((time.monotonic() - t0) * 1000)
        trace = ToolCallTrace(
            id=trace_id,
            tool=name,
            label=label,
            detail=detail,
            status="done",
            duration_ms=dur_ms,
            count=count,
            arguments=clean_args,
            result_summary=summary,
        )
        state.tools_used.append(trace)
        await emit("tool_done", trace.model_dump(mode="json"))
        return obs

    # ------------------------------------------------------------------
    # Graph mutuals & scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _current_match_bonus(profile: ProfileRecord, parsed: Optional[ParsedQuery]) -> float:
        if parsed is None:
            return 0.0
        bonus = 0.0
        cur_comp = normalize_company(profile.current_company)
        if cur_comp and any(
            normalize_company(rc) and normalize_company(rc) in cur_comp
            for rc in parsed.target_companies
        ):
            bonus += 0.12
        cur_role = strip_accents(profile.current_role or "").lower()
        if cur_role and any(
            strip_accents(rr).lower() in cur_role
            for rr in parsed.target_roles
        ):
            bonus += 0.08
        return bonus

    def _collect_mutuals_for_target(
        self,
        student_id: str,
        target: ProfileRecord,
        profile_by_id: dict[str, ProfileRecord],
        friend_profile: Optional[ProfileRecord],
    ) -> tuple[list[MutualContact], Optional[int]]:
        paths = self.graph_engine.find_connection_paths(
            student_id,
            target.id,
            max_hops=4,
            k_paths=3,
        )
        hop_count = paths[0].hop_count if paths else None

        mutuals: list[MutualContact] = []
        seen_ids: set[str] = set()

        for path in paths:
            if not path.hops:
                continue
            first_hop = path.hops[0]
            if first_hop.to_id == target.id or first_hop.to_id in seen_ids:
                continue
            seen_ids.add(first_hop.to_id)
            fh_prof = profile_by_id.get(first_hop.to_id)
            reason = first_hop.reason
            if len(path.hops) == 2:
                reason = f"{first_hop.reason} · connaît {target.full_name} ({path.hops[1].reason})"
            mutuals.append(
                MutualContact(
                    id=first_hop.to_id,
                    full_name=first_hop.to_name,
                    short_meta=fh_prof.to_profile_summary().short_meta if fh_prof else first_hop.to_meta,
                    reason=reason,
                    probability=first_hop.probability,
                    photo_url=fh_prof.photo_url if fh_prof else None,
                )
            )

        student_neighbors = {
            nid: (prob, reason)
            for nid, prob, reason in self.graph_engine.get_direct_neighbors(student_id)
        }
        target_neighbors = {
            nid: (prob, reason)
            for nid, prob, reason in self.graph_engine.get_direct_neighbors(target.id)
        }
        for shared_id in set(student_neighbors) & set(target_neighbors):
            if shared_id in seen_ids or shared_id in (student_id, target.id):
                continue
            prof = profile_by_id.get(shared_id)
            if prof is None:
                continue
            seen_ids.add(shared_id)
            prob_s, reason_s = student_neighbors[shared_id]
            _, reason_t = target_neighbors[shared_id]
            mutuals.append(
                MutualContact(
                    id=prof.id,
                    full_name=prof.full_name,
                    short_meta=prof.to_profile_summary().short_meta,
                    reason=f"{reason_s} · connaît {target.full_name} ({reason_t})",
                    probability=prob_s,
                    photo_url=prof.photo_url,
                )
            )

        if (
            friend_profile is not None
            and friend_profile.id not in (student_id, target.id)
            and friend_profile.id not in seen_ids
            and friend_profile.id in target_neighbors
        ):
            prob_t, reason_t = target_neighbors[friend_profile.id]
            mutuals.insert(
                0,
                MutualContact(
                    id=friend_profile.id,
                    full_name=friend_profile.full_name,
                    short_meta=friend_profile.to_profile_summary().short_meta,
                    reason=f"Connexion de {friend_profile.full_name} ({reason_t})",
                    probability=prob_t,
                    photo_url=friend_profile.photo_url,
                ),
            )

        return mutuals[:4], hop_count

    async def _generate_thinking_rationales(
        self,
        query: str,
        parsed: Optional[ParsedQuery],
        ranked_profiles: list[tuple[ProfileRecord, float]],
        explicit_criteria: list[str],
    ) -> dict[str, str]:
        if not ranked_profiles:
            return {}

        fallbacks = {
            prof.id: _build_deterministic_thinking(prof, parsed, rel, explicit_criteria)
            for prof, rel in ranked_profiles
        }
        if not isinstance(self.llm, VertexLLMService):
            return fallbacks

        payload = [
            {
                "id": prof.id,
                "full_name": prof.full_name,
                "current_role": _clean_role_or_company(prof.current_role),
                "current_company": _clean_role_or_company(prof.current_company),
                "sector": prof.sector,
                "location": prof.location,
                "promo_year": prof.promo_year,
                "bio": prof.bio,
                "experiences": prof.experiences[:4],
                "associations": prof.associations[:5],
                "passions": prof.passions[:5],
                "relevance_score": round(rel, 2),
            }
            for prof, rel in ranked_profiles
        ]
        prompt = (
            "Pour chacun des profils alumni ci-dessous, rédige une analyse honnête de 2 à 3 phrases en français "
            "expliquant pourquoi ce contact est pertinent (ou seulement adjacent) pour la requête.\n"
            "Règles strictes :\n"
            "- Appuie-toi UNIQUEMENT sur les champs fournis (rôle actuel, entreprise actuelle, expériences passées, bio, associations).\n"
            "- Si une entreprise ou un secteur recherché correspond uniquement à une expérience passée ou à un profil adjacent, dis-le explicitement.\n"
            "- N'invente aucun fait, aucune passion, aucun lien.\n"
            "- Réponds UNIQUEMENT en JSON valide sous la forme {\"<profile_id>\": \"<analyse en 2-3 phrases>\"}.\n\n"
            f"Requête : {query}\n"
            f"Profils : {json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            raw = await asyncio.to_thread(self.llm._generate_sync, prompt, temperature=0.2, schema=None)
            parsed_json = extract_json_fallback(raw)
            if isinstance(parsed_json, dict):
                merged = dict(fallbacks)
                for pid, txt in parsed_json.items():
                    if pid in merged and isinstance(txt, str) and txt.strip():
                        merged[pid] = txt.strip()
                return merged
        except Exception:
            pass
        return fallbacks

    # ------------------------------------------------------------------
    # Agent loops: Vertex Native Tool Calling, ReAct JSON, Deterministic
    # ------------------------------------------------------------------

    @staticmethod
    def _build_intro_for_first_tool(name: str, args: dict[str, Any]) -> str:
        if name == "search_alumni":
            friend = str(args.get("friend_name") or "").strip()
            if friend:
                return f"Je recherche dans les connexions de {friend} des profils pertinents."
            return "Je recherche dans le réseau CentraleSupélec les profils les plus pertinents."
        if name == "get_profile_details":
            return "Je consulte les détails du profil demandé dans l'annuaire."
        if name == "draft_intro_message":
            return "Je prépare un message d'introduction personnalisé."
        return "J'analyse ta demande avec le réseau CentraleSupélec."

    async def _run_vertex_native_loop(
        self,
        state: _TurnState,
        messages: list[ChatMessage],
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> tuple[str, list[dict[str, Any]]]:
        tools = _build_vertex_tools()
        system_instruction = _build_agent_system_prompt(state.student)
        contents: list[types.Content] = [
            types.Content(
                role="model" if m.role == "assistant" else "user",
                parts=[types.Part.from_text(text=m.content)],
            )
            for m in messages[-8:]
        ]
        config = types.GenerateContentConfig(
            tools=tools,
            system_instruction=system_instruction,
            temperature=0.15,
        )

        final_answer = ""
        selected_people: list[dict[str, Any]] = []

        for step in range(MAX_AGENT_STEPS):
            try:
                res = await asyncio.to_thread(
                    self.llm.client.models.generate_content,
                    model=self.llm.gemma_model,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                if step == 0 and not state.tools_used:
                    raise _NativeToolsUnsupported(str(exc)) from exc
                break

            fn_calls = list(getattr(res, "function_calls", None) or [])
            if fn_calls:
                if not state.intro_emitted:
                    first_fc = fn_calls[0]
                    intro = self._build_intro_for_first_tool(
                        str(first_fc.name),
                        dict(first_fc.args or {}),
                    )
                    state.intro_emitted = True
                    state.intro_text = intro
                    await emit("assistant_intro", {"intro_text": intro, "action": "agent"})

                candidates = getattr(res, "candidates", None) or []
                model_content = candidates[0].content if candidates and candidates[0].content else None
                if model_content is None:
                    model_content = types.Content(
                        role="model",
                        parts=[types.Part(function_call=fc) for fc in fn_calls],
                    )
                contents.append(model_content)

                response_parts: list[types.Part] = []
                for fc in fn_calls:
                    obs = await self._execute_tool(
                        str(fc.name),
                        dict(fc.args or {}),
                        state,
                        emit,
                    )
                    response_parts.append(
                        types.Part.from_function_response(name=str(fc.name), response=obs)
                    )
                contents.append(types.Content(role="user", parts=response_parts))
                continue

            raw_text = (getattr(res, "text", None) or "").strip()
            if raw_text.startswith("{"):
                try:
                    parsed = _ReactTurn.model_validate(extract_json_fallback(raw_text))
                    final_answer = parsed.final_answer or parsed.intro or raw_text
                    selected_people = parsed.selected_people
                except Exception:
                    final_answer = raw_text
            else:
                final_answer = raw_text
            break

        return final_answer, selected_people

    async def _run_react_json_loop(
        self,
        state: _TurnState,
        messages: list[ChatMessage],
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> tuple[str, list[dict[str, Any]]]:
        recent_msgs = [{"role": m.role, "content": m.content} for m in messages[-8:]]
        scratchpad: list[dict[str, Any]] = []
        final_answer = ""
        selected_people: list[dict[str, Any]] = []

        for step in range(MAX_AGENT_STEPS):
            prompt = (
                f"{_build_agent_system_prompt(state.student)}\n\n"
                f"Historique récent : {json.dumps(recent_msgs, ensure_ascii=False)}\n"
                f"Observations des étapes précédentes : {json.dumps(scratchpad, ensure_ascii=False)}\n\n"
                "Réponds UNIQUEMENT en JSON valide selon le format :\n"
                '{"thought": "...", "intro": "courte phrase d\'introduction en français", '
                '"tool_calls": [{"name": "...", "arguments": {...}}], '
                '"final_answer": "...", "selected_people": [{"id": "...", "thinking": "..."}]}\n'
                "- Si tu veux appeler un ou plusieurs outils, mets-les dans tool_calls et laisse final_answer vide.\n"
                "- Si tu as toutes les observations nécessaires pour répondre, laisse tool_calls=[] et remplis final_answer."
            )
            raw = await asyncio.to_thread(self.llm._generate_sync, prompt, temperature=0.15, schema=None)
            turn = _ReactTurn.model_validate(extract_json_fallback(raw))

            if turn.intro.strip() and not state.intro_emitted:
                state.intro_emitted = True
                state.intro_text = turn.intro.strip()
                await emit("assistant_intro", {"intro_text": state.intro_text, "action": "agent"})

            if turn.tool_calls:
                for tc in turn.tool_calls:
                    t_name = str(tc.get("name") or "")
                    t_args = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
                    obs = await self._execute_tool(t_name, t_args, state, emit)
                    scratchpad.append({"tool": t_name, "arguments": t_args, "observation": obs})
                continue

            final_answer = turn.final_answer.strip() or turn.intro.strip()
            selected_people = turn.selected_people
            break

        return final_answer, selected_people

    @staticmethod
    def _extract_draft_names_from_text(
        last_user: str,
        messages: list[ChatMessage],
        all_profiles: list[ProfileRecord],
        student_id: str,
    ) -> tuple[Optional[str], Optional[str]]:
        patterns_fh_then_target = [
            r"(?:demande[rz]?\s+a|ecri(?:re|s)\s+a|message\s+a)\s+([A-Za-zÀ-ÿ\-']+(?:\s+[A-Za-zÀ-ÿ\-']+)?)\s+(?:de\s+(?:me\s+)?presenter|pour\s+(?:me\s+)?presenter|pour\s+contacter)\s+([A-Za-zÀ-ÿ\-']+(?:\s+[A-Za-zÀ-ÿ\-']+)?)",
            r"via\s+([A-Za-zÀ-ÿ\-']+(?:\s+[A-Za-zÀ-ÿ\-']+)?)\s+pour\s+(?:contacter|joindre|parler\s+a)\s+([A-Za-zÀ-ÿ\-']+(?:\s+[A-Za-zÀ-ÿ\-']+)?)",
        ]
        for pat in patterns_fh_then_target:
            m = re.search(pat, strip_accents(last_user), flags=re.IGNORECASE)
            if m:
                fh = _match_profile_by_name(m.group(1), all_profiles, exclude_id=student_id)
                tg = _match_profile_by_name(m.group(2), all_profiles, exclude_id=student_id)
                if fh and tg:
                    return fh.full_name, tg.full_name

        m_rev = re.search(
            r"(?:contacter|pour)\s+([A-Za-zÀ-ÿ\-']+(?:\s+[A-Za-zÀ-ÿ\-']+)?)\s+(?:via|par)\s+([A-Za-zÀ-ÿ\-']+(?:\s+[A-Za-zÀ-ÿ\-']+)?)",
            strip_accents(last_user),
            flags=re.IGNORECASE,
        )
        if m_rev:
            tg = _match_profile_by_name(m_rev.group(1), all_profiles, exclude_id=student_id)
            fh = _match_profile_by_name(m_rev.group(2), all_profiles, exclude_id=student_id)
            if fh and tg:
                return fh.full_name, tg.full_name

        mentioned = _find_mentioned_profiles(last_user, all_profiles, exclude_id=student_id)
        if not mentioned:
            history_text = " ".join(m.content for m in reversed(messages[:-1]))
            mentioned = _find_mentioned_profiles(history_text, all_profiles, exclude_id=student_id)

        if len(mentioned) >= 2:
            return mentioned[0].full_name, mentioned[1].full_name
        if len(mentioned) == 1:
            return None, mentioned[0].full_name
        return None, None

    @staticmethod
    def _is_profile_followup(
        last_user: str,
        friend_filter: Optional[str],
        mentioned: list[ProfileRecord],
    ) -> bool:
        if friend_filter or not mentioned:
            return False
        norm = strip_accents(last_user).lower()
        if any(hint in norm for hint in _SEARCH_FOR_OTHERS_HINTS):
            return False
        if "travaille avec" in norm or "travaille chez" in norm:
            return False
        return any(hint in norm for hint in _PROFILE_QA_HINTS)

    async def _run_deterministic_loop(
        self,
        state: _TurnState,
        messages: list[ChatMessage],
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Deterministic multi-step tool-calling loop over the exact same 6 tools."""
        user_msgs = [m.content.strip() for m in messages if m.role == "user" and m.content.strip()]
        last_user = user_msgs[-1] if user_msgs else ""
        norm_last = strip_accents(last_user).lower().strip()
        mentioned_now = _find_mentioned_profiles(last_user, state.all_profiles, exclude_id=state.student.id)

        # 1. Draft intent
        draft_verb = bool(
            re.search(r"\b(redige[rz]?|ecri[st]|ecrire|prepare[rz]?|genere[rz]?|draft)\b", norm_last)
        )
        draft_noun = bool(
            re.search(r"\bmessage\s+(?:d['’]?intro|pour|a)\b", norm_last)
            or ("message" in norm_last and bool(mentioned_now))
        )
        is_draft = (
            draft_verb
            and (
                "message" in norm_last
                or "intro" in norm_last
                or "mail" in norm_last
                or "linkedin" in norm_last
                or bool(mentioned_now)
            )
        ) or draft_noun

        if is_draft:
            first_hop_name, target_name = self._extract_draft_names_from_text(
                last_user, messages, state.all_profiles, state.student.id
            )
            target = _match_profile_by_name(target_name, state.all_profiles, exclude_id=state.student.id)
            first_hop = _match_profile_by_name(first_hop_name, state.all_profiles, exclude_id=state.student.id)
            if target is None and first_hop is not None:
                target, first_hop = first_hop, None

            intro = (
                f"Je prépare un message d'introduction pour contacter {target.full_name}."
                if target
                else "Je prépare un message d'introduction personnalisé."
            )
            state.intro_emitted = True
            state.intro_text = intro
            await emit("assistant_intro", {"intro_text": intro, "action": "draft"})

            if target is None:
                return (
                    "Je n'ai pas identifié la personne à contacter dans l'annuaire. "
                    "Précise son prénom et son nom pour que je rédige le message.",
                    [],
                )

            if first_hop is None:
                paths = self.graph_engine.find_connection_paths(state.student.id, target.id, max_hops=4, k_paths=1)
                if paths and paths[0].hops:
                    first_hop = state.profile_by_id.get(paths[0].hops[0].to_id) or target
                else:
                    first_hop = target

            await self._execute_tool(
                "draft_intro_message",
                {"first_hop_id": first_hop.id, "target_id": target.id, "context": last_user},
                state,
                emit,
            )
            await self._execute_tool(
                "find_mutual_connections",
                {"target_ids": [target.id]},
                state,
                emit,
            )
            return "", []

        # 2. Extract optional friend_filter & check profile follow-up Q&A
        friend_filter, remainder_query = _extract_friend_filter_from_text(last_user)
        if self._is_profile_followup(last_user, friend_filter, mentioned_now):
            targets = mentioned_now[:2]
            intro = f"Je consulte la fiche détaillée de {targets[0].full_name}."
            state.intro_emitted = True
            state.intro_text = intro
            await emit("assistant_intro", {"intro_text": intro, "action": "profile_qa"})

            inspected_records: list[ProfileRecord] = []
            to_enrich: list[str] = []
            for prof in targets:
                await self._execute_tool("get_profile_details", {"profile_id": prof.id}, state, emit)
                if self.enrichment.is_web_enabled() and self.enrichment.needs_enrichment(prof):
                    to_enrich.append(prof.id)

            if to_enrich:
                await self._execute_tool("enrich_alumni_profiles", {"profile_ids": to_enrich}, state, emit)
                for pid in to_enrich:
                    await self._execute_tool("get_profile_details", {"profile_id": pid}, state, emit)

            for pid in state.inspected_profile_ids:
                if pid in state.profile_by_id:
                    inspected_records.append(state.profile_by_id[pid])

            return _build_profile_qa_prose(inspected_records), []

        # 3. Resolve effective search query + multi-turn inheritance
        effective_query = remainder_query if _has_substantive_terms(remainder_query) else ""
        if not effective_query and friend_filter and len(user_msgs) >= 2:
            for prev in reversed(user_msgs[:-1]):
                _, prev_rem = _extract_friend_filter_from_text(prev)
                if _has_substantive_terms(prev_rem):
                    effective_query = prev_rem
                    break
        if not effective_query:
            effective_query = last_user

        meaningful_tokens = [
            tok
            for tok in re.findall(r"[a-z0-9]{2,}", strip_accents(effective_query).lower())
            if tok not in _GREETING_TOKENS
        ]
        if not friend_filter and len(meaningful_tokens) < 2 and len(norm_last) < 20:
            clarify_msg = (
                "Dis-moi quel secteur, entreprise, poste ou association tu vises "
                "(par exemple : « stage de césure dans l'énergie chez Engie » ou "
                "« trouve dans les amis de Thomas quelqu'un chez Doctolib »)."
            )
            state.intro_emitted = True
            state.intro_text = clarify_msg
            await emit("assistant_intro", {"intro_text": clarify_msg, "action": "clarify"})
            return clarify_msg, []

        parsed = await self.llm.parse_user_query(effective_query)
        friend_profile = _match_profile_by_name(friend_filter, state.all_profiles, exclude_id=state.student.id)
        if friend_profile is not None:
            intro = (
                f"Je vais chercher dans les connexions de {friend_profile.full_name} "
                "des profils pertinents pour ta recherche."
            )
        elif friend_filter:
            intro = f"Je recherche « {friend_filter} » et les profils correspondants dans l'annuaire."
        else:
            focus = parsed.summary_label or effective_query
            intro = f"Je recherche dans le réseau CentraleSupélec des profils pertinents ({focus})."

        state.intro_emitted = True
        state.intro_text = intro
        await emit("assistant_intro", {"intro_text": intro, "action": "search"})

        # Step 1: search_alumni
        search_obs = await self._execute_tool(
            "search_alumni",
            {
                "query": effective_query,
                "sector": parsed.target_sector or "",
                "company": parsed.target_companies[0] if parsed.target_companies else "",
                "role": parsed.target_roles[0] if parsed.target_roles else "",
                "friend_name": friend_filter or "",
                "limit": 10,
            },
            state,
            emit,
        )
        if search_obs.get("status") == "friend_not_found":
            return "", []

        # Step 2: web_search_alumni when web enabled and DB results sparse or missing requested company
        current_cands = list(state.candidates_by_id.values())
        if self.enrichment.is_web_enabled() and SearchAgentService._should_run_web_discovery(current_cands, parsed):
            web_queries = [effective_query]
            if parsed.target_companies:
                web_queries.insert(0, f"CentraleSupélec {' '.join(parsed.target_companies[:2])}")
            await self._execute_tool(
                "web_search_alumni",
                {"queries": web_queries[:2]},
                state,
                emit,
            )

        # Step 3: enrich_alumni_profiles on uncached top candidates
        if self.enrichment.is_web_enabled():
            ranked_ids = sorted(
                state.candidates_by_id.keys(),
                key=lambda pid: (
                    state.relevance_by_id.get(pid, 0.0)
                    + self._current_match_bonus(state.candidates_by_id[pid].profile, state.last_parsed)
                ),
                reverse=True,
            )
            uncached_ids = [
                pid
                for pid in ranked_ids[:8]
                if self.enrichment.needs_enrichment(state.candidates_by_id[pid].profile)
            ][:6]
            if uncached_ids:
                await self._execute_tool(
                    "enrich_alumni_profiles",
                    {"profile_ids": uncached_ids},
                    state,
                    emit,
                )

        # Step 4: find_mutual_connections on top filtered candidates
        selected_profiles = self._select_filtered_profiles(state, max_results=8)
        if selected_profiles:
            await self._execute_tool(
                "find_mutual_connections",
                {"target_ids": [p.id for p in selected_profiles]},
                state,
                emit,
            )

        return "", []

    # ------------------------------------------------------------------
    # Noise filtering & final response grounding
    # ------------------------------------------------------------------

    def _select_filtered_profiles(
        self,
        state: _TurnState,
        *,
        preferred_ids: Optional[list[str]] = None,
        max_results: int = 8,
    ) -> list[ProfileRecord]:
        """Rank candidates and exclude non-relevant unenriched noise when strong matches exist."""
        if not state.candidates_by_id and preferred_ids:
            for pid in preferred_ids:
                prof = state.profile_by_id.get(pid)
                if prof and prof.id != state.student.id:
                    state.candidates_by_id[pid] = SearchCandidate(profile=prof, hybrid_score=0.5, semantic_score=0.5)

        if not state.candidates_by_id:
            return []

        parsed = state.last_parsed or ParsedQuery()
        det_vec = state.det_query_vec or deterministic_text_embedding(state.last_query or "", dim=768)
        vertex_vec = state.vertex_query_vec or det_vec

        scored: list[tuple[float, float, bool, ProfileRecord]] = []
        for pid, cand in state.candidates_by_id.items():
            if pid == state.student.id:
                continue
            if state.allowed_ids is not None and pid not in state.allowed_ids:
                continue
            rel = _compute_profile_relevance(
                cand,
                det_vec,
                vertex_vec,
                parsed,
                raw_query=state.last_query,
                discovered_ids=state.discovered_ids,
            )
            state.relevance_by_id[pid] = rel
            bonus = self._current_match_bonus(cand.profile, parsed)
            enriched = _is_enriched_profile(cand.profile)
            scored.append((rel + bonus, rel, enriched, cand.profile))

        if not scored:
            return []

        has_strong_match = any(rel >= 0.35 for _, rel, _, _ in scored)
        has_relevant_enriched = any(rel >= 0.22 and enr for _, rel, enr, _ in scored)
        has_any_enriched = any(enr for _, _, enr, _ in scored)

        filtered: list[tuple[float, float, bool, ProfileRecord]] = []
        for row in scored:
            _, rel, enriched, _ = row
            if has_strong_match and rel < 0.22:
                continue
            if has_relevant_enriched and rel < 0.22 and not enriched:
                continue
            if has_any_enriched and not enriched and rel < 0.22:
                continue
            filtered.append(row)

        if not filtered:
            filtered = scored

        preferred_set = [pid for pid in (preferred_ids or []) if any(row[3].id == pid for row in filtered)]
        if preferred_set:
            by_id = {row[3].id: row[3] for row in filtered}
            return [by_id[pid] for pid in dict.fromkeys(preferred_set) if pid in by_id][:max_results]

        filtered.sort(
            key=lambda row: (1 if row[1] >= 0.22 else 0, row[0]),
            reverse=True,
        )
        return [row[3] for row in filtered[:max_results]]

    async def _finalize_response(
        self,
        state: _TurnState,
        final_answer: str,
        selected_people_hints: list[dict[str, Any]],
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
        t0: float,
    ) -> ChatResponse:
        if not state.intro_emitted:
            intro = final_answer or state.intro_text or "Voici les résultats de ma recherche dans le réseau."
            state.intro_emitted = True
            state.intro_text = intro
            await emit("assistant_intro", {"intro_text": intro, "action": "final"})

        # Case A: Drafted outreach message
        if state.drafted_message is not None and state.draft_target is not None:
            target = state.draft_target
            first_hop = state.draft_first_hop or target
            if target.id not in state.mutuals_by_id:
                muts, hops = self._collect_mutuals_for_target(
                    state.student.id, target, state.profile_by_id, state.friend_profile
                )
                state.mutuals_by_id[target.id] = (muts, hops)
            muts, hops = state.mutuals_by_id.get(target.id, ([], None))

            intro_text = final_answer or (
                f"Voici un message prêt à envoyer à {first_hop.full_name} pour demander une mise en relation avec {target.full_name} :"
                if first_hop.id != target.id
                else f"Voici un message prêt à envoyer directement à {target.full_name} :"
            )
            outro_text = (
                f"Points communs vérifiés utilisés : {state.draft_verified_common_points}."
                if state.draft_verified_common_points
                else ""
            )
            total_ms = int((time.monotonic() - t0) * 1000)
            response = ChatResponse(
                intro_text=intro_text,
                outro_text=outro_text,
                tools_used=state.tools_used,
                total_duration_ms=total_ms,
                total_candidates=max(state.total_candidates, 1),
                people=[
                    ChatPersonResult(
                        id=target.id,
                        full_name=target.full_name,
                        role_company=_format_role_company(target),
                        location=target.location.strip() if target.location and target.location.strip() else None,
                        thinking=target.bio or f"{_format_role_company(target)}.",
                        source_url=target.linkedin_url,
                        source_label="LinkedIn" if target.linkedin_url else None,
                        photo_url=target.photo_url,
                        mutuals=muts,
                        hop_count=hops,
                    )
                ],
                drafted_message=state.drafted_message,
            )
            await emit("final_result", {"response": response.model_dump(mode="json")})
            return response

        # Case B: Profile Q&A / pure prose follow-up (get_profile_details without search)
        if state.inspected_profile_ids and not state.candidates_by_id and not selected_people_hints:
            inspected = [
                state.profile_by_id[pid]
                for pid in state.inspected_profile_ids
                if pid in state.profile_by_id
            ]
            prose = final_answer.strip() if final_answer.strip() else _build_profile_qa_prose(inspected)
            total_ms = int((time.monotonic() - t0) * 1000)
            response = ChatResponse(
                intro_text=prose,
                outro_text="",
                tools_used=state.tools_used,
                total_duration_ms=total_ms,
                total_candidates=0,
                people=[],
            )
            await emit("final_result", {"response": response.model_dump(mode="json")})
            return response

        # Case C: Friend not found
        if state.friend_not_found_name and not state.candidates_by_id:
            total_ms = int((time.monotonic() - t0) * 1000)
            response = ChatResponse(
                intro_text=state.intro_text or final_answer,
                outro_text=f"Aucun membre nommé « {state.friend_not_found_name} » n'a été trouvé dans l'annuaire.",
                tools_used=state.tools_used,
                total_duration_ms=total_ms,
                total_candidates=0,
                people=[],
            )
            await emit("final_result", {"response": response.model_dump(mode="json")})
            return response

        # Case D: Pure clarify / prose without candidates
        preferred_ids = [
            str(item.get("id"))
            for item in selected_people_hints
            if isinstance(item, dict) and item.get("id")
        ]
        selected_profiles = self._select_filtered_profiles(state, preferred_ids=preferred_ids, max_results=8)
        if not selected_profiles:
            total_ms = int((time.monotonic() - t0) * 1000)
            outro = ""
            if state.tools_used:
                outro = (
                    f"Aucune connexion de {state.friend_profile.full_name} ne correspond encore à cette recherche."
                    if state.friend_profile
                    else "Aucun profil correspondant trouvé dans la base actuelle."
                )
            response = ChatResponse(
                intro_text=final_answer.strip() or state.intro_text,
                outro_text=outro,
                tools_used=state.tools_used,
                total_duration_ms=total_ms,
                total_candidates=0,
                people=[],
            )
            await emit("final_result", {"response": response.model_dump(mode="json")})
            return response

        # Case E: Search results with grounded rationales & mutuals
        missing_mutual_ids = [p.id for p in selected_profiles if p.id not in state.mutuals_by_id]
        if missing_mutual_ids:
            already_called_mutuals = any(t.tool == "find_mutual_connections" for t in state.tools_used)
            if not already_called_mutuals:
                await self._execute_tool(
                    "find_mutual_connections",
                    {"target_ids": missing_mutual_ids},
                    state,
                    emit,
                )
            else:
                for p in selected_profiles:
                    if p.id not in state.mutuals_by_id:
                        state.mutuals_by_id[p.id] = self._collect_mutuals_for_target(
                            state.student.id, p, state.profile_by_id, state.friend_profile
                        )

        parsed = state.last_parsed or ParsedQuery()
        explicit_criteria = [
            *parsed.target_companies,
            *parsed.target_roles,
            *([parsed.target_sector] if parsed.target_sector else []),
        ]
        hint_thinking = {
            str(item["id"]): str(item["thinking"]).strip()
            for item in selected_people_hints
            if isinstance(item, dict) and item.get("id") and isinstance(item.get("thinking"), str) and item["thinking"].strip()
        }

        profiles_needing_rationale = [
            (p, state.relevance_by_id.get(p.id, 0.0))
            for p in selected_profiles
            if p.id not in hint_thinking
        ]
        generated_rationales = await self._generate_thinking_rationales(
            state.last_query,
            parsed,
            profiles_needing_rationale,
            explicit_criteria,
        )

        people: list[ChatPersonResult] = []
        for prof in selected_profiles:
            muts, hops = state.mutuals_by_id.get(prof.id, ([], None))
            thinking_txt = hint_thinking.get(prof.id) or generated_rationales.get(prof.id, "")
            people.append(
                ChatPersonResult(
                    id=prof.id,
                    full_name=prof.full_name,
                    role_company=_format_role_company(prof),
                    location=prof.location.strip() if prof.location and prof.location.strip() else None,
                    thinking=thinking_txt,
                    source_url=prof.linkedin_url,
                    source_label="LinkedIn" if prof.linkedin_url else None,
                    photo_url=prof.photo_url,
                    mutuals=muts,
                    hop_count=hops,
                )
            )

        has_strong_match = any(state.relevance_by_id.get(p.id, 0.0) >= 0.35 for p in selected_profiles)
        outro_text = ""
        if explicit_criteria and not has_strong_match:
            outro_text = (
                f"Aucun match exact trouvé pour « {' / '.join(explicit_criteria)} » ; "
                "les profils ci-dessus sont les plus proches identifiés dans le réseau."
            )
        elif final_answer.strip() and final_answer.strip() != state.intro_text.strip():
            outro_text = final_answer.strip()

        total_ms = int((time.monotonic() - t0) * 1000)
        response = ChatResponse(
            intro_text=state.intro_text,
            outro_text=outro_text,
            tools_used=state.tools_used,
            total_duration_ms=total_ms,
            total_candidates=max(state.total_candidates, len(people)),
            people=people,
        )
        await emit("final_result", {"response": response.model_dump(mode="json")})
        return response

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def run_chat(
        self,
        student_id: str,
        messages: list[ChatMessage],
        *,
        event_callback: Optional[ChatEventCallback] = None,
    ) -> ChatResponse:
        t0 = time.monotonic()

        async def emit(ev_name: str, payload: dict[str, Any]) -> None:
            if event_callback is not None:
                await event_callback(ev_name, payload)

        student = await self.repository.get_profile(student_id)
        if student is None:
            raise ValueError(f"Profil étudiant introuvable: {student_id}")

        all_profiles = await self.repository.list_profiles()
        state = _TurnState(
            student=student,
            all_profiles=all_profiles,
            profile_by_id={p.id: p for p in all_profiles},
        )

        final_answer = ""
        selected_people_hints: list[dict[str, Any]] = []

        has_vertex_client = hasattr(self.llm, "client") and hasattr(self.llm, "gemma_model")
        if has_vertex_client:
            try:
                final_answer, selected_people_hints = await self._run_vertex_native_loop(state, messages, emit)
            except _NativeToolsUnsupported:
                try:
                    final_answer, selected_people_hints = await self._run_react_json_loop(state, messages, emit)
                except Exception:
                    if not state.tools_used:
                        final_answer, selected_people_hints = await self._run_deterministic_loop(state, messages, emit)
        elif hasattr(self.llm, "_generate_sync"):
            try:
                final_answer, selected_people_hints = await self._run_react_json_loop(state, messages, emit)
            except Exception:
                if not state.tools_used:
                    final_answer, selected_people_hints = await self._run_deterministic_loop(state, messages, emit)
        else:
            final_answer, selected_people_hints = await self._run_deterministic_loop(state, messages, emit)

        return await self._finalize_response(state, final_answer, selected_people_hints, emit, t0)
