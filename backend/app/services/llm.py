"""Vertex AI (Gemma 4 + gemini-embedding-2) and deterministic offline LLM services."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from typing import Optional, Protocol

import numpy as np
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.db.repository import ProfileRecord
from app.schemas.profile import EnrichedProfile, Experience
from app.schemas.search import HopDetail, ParsedQuery
from app.services.graph_engine import normalize_association, normalize_company, strip_accents

_FR_STOPWORDS = {
    "je", "tu", "il", "elle", "nous", "vous", "ils", "elles", "un", "une", "des",
    "le", "la", "les", "du", "de", "d", "et", "ou", "dans", "en", "sur", "avec",
    "pour", "qui", "que", "quoi", "cherche", "veux", "voudrais", "trouver", "boite",
    "entreprise", "travaille", "alumni", "etudiant", "etudiante", "bonjour", "merci",
    "mon", "ma", "mes", "a", "au", "aux", "est", "sont",
}

_SYNONYM_BRIDGES: dict[str, tuple[str, ...]] = {
    "trail": ("course", "montagne", "running", "runner", "maraton", "marathon"),
    "course": ("trail", "running", "runner", "montagne"),
    "energie": ("renouvelable", "solaire", "nucleaire", "climat", "decarbonee", "edf", "engie", "totalenergies"),
    "ia": ("intelligence", "artificielle", "ml", "machine", "learning", "llm", "generative", "data", "mistral"),
    "generative": ("llm", "ia", "modeles", "langage", "ai"),
    "sante": ("healthtech", "doctolib", "alan", "medical", "product"),
    "quant": ("finance", "banque", "marches", "trading", "investissement", "risques", "bnp"),
    "fintech": ("startup", "entrepreneur", "fondateur", "qonto", "paiement", "levee"),
    "pm": ("product", "manager", "produit"),
    "product": ("pm", "produit"),
}


def extract_json_fallback(raw_text: str) -> dict:
    """Extract a JSON object even when wrapped in markdown fences or surrounding text."""
    cleaned = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        brace_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(1)
    return json.loads(cleaned)


def deterministic_text_embedding(text: str, dim: int = 768) -> list[float]:
    """Generate a reproducible L2-normalized semantic-hashed embedding for offline/test mode."""
    vec = np.zeros(dim, dtype=np.float32)
    norm = strip_accents(text).lower()
    tokens = [t for t in re.findall(r"[a-z0-9]{2,}", norm) if t not in _FR_STOPWORDS]

    expanded: list[tuple[str, float]] = []
    for tok in tokens:
        expanded.append((tok, 1.0))
        if len(tok) >= 5:
            expanded.append((tok[:5], 0.5))
        for syn in _SYNONYM_BRIDGES.get(tok, ()):
            expanded.append((syn, 0.7))
    for i in range(len(tokens) - 1):
        expanded.append((f"{tokens[i]}_{tokens[i + 1]}", 0.8))

    for feature, weight in expanded:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "little")
        idx = h % dim
        sign = 1.0 if ((h >> 17) & 1) == 0 else -1.0
        vec[idx] += sign * weight

    norm_val = float(np.linalg.norm(vec))
    if norm_val > 0.0:
        vec /= norm_val
    return vec.tolist()


def compute_verified_common_points(student: ProfileRecord, other: ProfileRecord) -> list[str]:
    """Return ONLY strictly verified shared associations, passions, companies, or cohort links."""
    points: list[str] = []

    student_assos = {normalize_association(a): a for a in student.associations if normalize_association(a)}
    other_assos = {normalize_association(a): a for a in other.associations if normalize_association(a)}
    for key in sorted(set(student_assos) & set(other_assos)):
        points.append(f"Association commune : {student_assos[key]}")

    student_passions = {strip_accents(p).lower().strip(): p for p in student.passions if p.strip()}
    other_passions = {strip_accents(p).lower().strip(): p for p in other.passions if p.strip()}
    for sk, s_disp in student_passions.items():
        if sk in other_passions:
            points.append(f"Passion commune : {s_disp}")

    student_companies = {
        normalize_company(e.get("company")): e.get("company", "")
        for e in student.experiences
        if normalize_company(e.get("company"))
    }
    if student.current_company and normalize_company(student.current_company):
        student_companies[normalize_company(student.current_company)] = student.current_company

    other_companies = {
        normalize_company(e.get("company")): e.get("company", "")
        for e in other.experiences
        if normalize_company(e.get("company"))
    }
    if other.current_company and normalize_company(other.current_company):
        other_companies[normalize_company(other.current_company)] = other.current_company

    for c_key in sorted(set(student_companies) & set(other_companies)):
        points.append(f"Expérience commune chez {other_companies[c_key]}")

    if student.promo_year and other.promo_year:
        if abs(student.promo_year - other.promo_year) <= 2:
            points.append(f"CentraleSupélec (promos proches {student.promo_year}/{other.promo_year})")
        else:
            points.append("Réseau CentraleSupélec")
    else:
        points.append("Réseau CentraleSupélec")

    return points


def _sanitize_outreach_text(text: str, fallback: str) -> str:
    cleaned = text.strip().strip('"').strip("'")
    # Reject accidental bracket placeholders such as [Nom] or [Prénom]
    if re.search(r"\[[^\]]{1,40}\]", cleaned):
        return fallback
    words = cleaned.split()
    if len(words) > 95:
        cleaned = " ".join(words[:90]).rstrip(",;:") + "."
    return cleaned or fallback


class LLMServiceProtocol(Protocol):
    async def parse_user_query(self, query: str) -> ParsedQuery: ...

    async def extract_profile_from_snippets(self, full_name: str, snippets: str) -> EnrichedProfile: ...

    async def generate_outreach_message(
        self,
        student: ProfileRecord,
        first_hop: ProfileRecord,
        target: ProfileRecord,
        hops: list[HopDetail],
        intent: str,
        common_points: list[str],
        extra_context: Optional[str] = None,
    ) -> str: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicLLMService:
    """Zero-network deterministic LLM & embedding implementation for unit tests and offline mode."""

    def __init__(self, embedding_dim: int = 768) -> None:
        self.embedding_dim = embedding_dim

    async def parse_user_query(self, query: str) -> ParsedQuery:
        q_norm = strip_accents(query).lower()

        sector: Optional[str] = None
        if any(k in q_norm for k in ("energie", "solaire", "nucleaire", "renouvelable", "climat")):
            sector = "Énergie"
        elif any(k in q_norm for k in ("sante", "healthtech", "doctolib", "medical")):
            sector = "Santé / Tech"
        elif any(k in q_norm for k in ("ia", "intelligence artificielle", "ml", "machine learning", "llm", "data")):
            sector = "Intelligence Artificielle"
        elif any(k in q_norm for k in ("quant", "finance", "banque", "trading", "investissement")):
            sector = "Finance"
        elif any(k in q_norm for k in ("fintech", "startup", "entrepreneur", "fondateur")):
            sector = "Fintech"
        elif "vc" in q_norm or "venture" in q_norm:
            sector = "Venture Capital"

        known_companies = [
            "Mistral AI", "Ekimetrics", "Doctolib", "TotalEnergies", "EDF", "Engie",
            "Schneider Electric", "Qair", "Alan", "BNP Paribas", "Société Générale",
            "Qonto", "Partech", "Withings", "GreenTech Energy",
        ]
        companies = [c for c in known_companies if strip_accents(c).lower() in q_norm]

        roles: list[str] = []
        role_map = [
            ("product manager", "Product Manager"),
            ("pm", "Product Manager"),
            ("ml engineer", "ML Engineer"),
            ("data scientist", "Data Scientist"),
            ("quant", "Quantitative Analyst"),
            ("fondateur", "Fondateur"),
            ("cofondateur", "Cofondateur"),
            ("vp engineering", "VP Engineering"),
        ]
        for needle, label in role_map:
            if re.search(rf"\b{re.escape(needle)}\b", q_norm) and label not in roles:
                roles.append(label)

        worked_with: Optional[str] = None
        ww_match = re.search(r"travaille\s+(?:avec|chez)\s+([A-Za-zÀ-ÿ0-9\s\-]{2,35})", query, flags=re.IGNORECASE)
        if ww_match:
            worked_with = ww_match.group(1).strip().rstrip("?.!")

        icebreakers: list[str] = []
        for kw in ("trail", "course", "bds", "bde", "junior centralesupelec", "club energie", "data club", "incubateur", "voile", "tennis", "natation", "finance"):
            if kw in q_norm:
                icebreakers.append(kw)

        intent = "conseil carrière"
        if "cesure" in q_norm:
            intent = "stage de césure"
        elif "stage" in q_norm:
            intent = "stage"
        elif any(k in q_norm for k in ("lancer", "startup", "creer")):
            intent = "lancement de startup"
        elif any(k in q_norm for k in ("metier", "comprendre", "echanger")):
            intent = "découverte métier"

        summary_parts = [intent.capitalize()]
        if sector:
            summary_parts.append(f"secteur {sector}")
        elif companies:
            summary_parts.append(", ".join(companies))
        return ParsedQuery(
            target_sector=sector,
            target_companies=companies,
            target_roles=roles,
            worked_with=worked_with,
            icebreakers=icebreakers,
            intent=intent,
            summary_label=" · ".join(summary_parts),
            limit=3,
        )

    async def extract_profile_from_snippets(self, full_name: str, snippets: str) -> EnrichedProfile:
        if not snippets.strip():
            return EnrichedProfile()

        norm_name = re.sub(r"\s+", " ", strip_accents(full_name).lower()).strip()
        norm_snippets = re.sub(r"\s+", " ", strip_accents(snippets).lower())
        if norm_name and norm_name not in norm_snippets:
            return EnrichedProfile()

        lines = [line.strip("-• \t") for line in snippets.splitlines() if line.strip()]
        raw_first = lines[0] if lines else ""
        # Strip snippet formatting prefix "[Title] (https://...): content"
        cleaned_first = re.sub(r"^\[[^\]]*\]\s*\([^)]*\)\s*:\s*", "", raw_first).strip()
        cleaned_first = re.sub(r"https?://\S+", "", cleaned_first).strip()
        bio = cleaned_first[:240] if cleaned_first else ""

        experiences: list[dict[str, str]] = []
        exp_matches = re.findall(
            r"([A-Za-zÀ-ÿ\s]{2,35}?)\s+(?:chez|at)\s+([A-Za-zÀ-ÿ0-9\s\-&]{2,35}?)(?:\s*\((\d{4}(?:\s*-\s*(?:\d{4}|Present))?)\))?(?:[.,;\n]|$)",
            snippets,
            flags=re.IGNORECASE,
        )
        for role, comp, period in exp_matches[:4]:
            role_clean = role.strip()
            comp_clean = comp.strip()
            if "employed" in role_clean.lower() or "research" in role_clean.lower():
                continue
            experiences.append(
                {
                    "role": role_clean,
                    "company": comp_clean,
                    "period": period.strip() if period else None,
                }
            )

        associations: list[str] = []
        for candidate in (
            "BDS", "BDE", "Junior CentraleSupélec", "Club Énergie",
            "Data Club", "Club Finance", "Incubateur", "CentraleSupélec Runner",
        ):
            if strip_accents(candidate).lower() in norm_snippets:
                associations.append(candidate)

        passions: list[str] = []
        passion_match = re.search(r"passions?\s*:\s*([^\n.]+)", snippets, flags=re.IGNORECASE)
        if passion_match:
            for item in passion_match.group(1).split(","):
                cleaned = item.strip()
                if cleaned:
                    passions.append(cleaned)

        first_company = experiences[0]["company"] if experiences else None
        first_role = experiences[0]["role"] if experiences else None
        name_tokens = [t for t in re.findall(r"[a-z0-9]{2,}", norm_name)]
        linkedin_url: Optional[str] = None
        for m in re.finditer(r"https?://(?:[a-z]+\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+", snippets, flags=re.IGNORECASE):
            cand_url = m.group(0).rstrip(").,;")
            slug = cand_url.lower().split("/in/", 1)[1]
            if len(name_tokens) >= 2 and name_tokens[0] in slug and name_tokens[-1] in slug:
                linkedin_url = cand_url
                break

        return EnrichedProfile(
            bio=bio,
            current_role=first_role,
            current_company=first_company,
            linkedin_url=linkedin_url,
            experiences=experiences,
            associations=associations,
            passions=passions,
        )

    async def generate_outreach_message(
        self,
        student: ProfileRecord,
        first_hop: ProfileRecord,
        target: ProfileRecord,
        hops: list[HopDetail],
        intent: str,
        common_points: list[str],
        extra_context: Optional[str] = None,
    ) -> str:
        first_name = first_hop.full_name.split()[0]
        promo_txt = f"promo {student.promo_year}" if student.promo_year else "étudiant à CentraleSupélec"
        shared_clause = ""
        asso_points = [p.split(":", 1)[1].strip() for p in common_points if p.startswith("Association commune")]
        exp_points = [p.replace("Expérience commune chez ", "") for p in common_points if p.startswith("Expérience commune")]
        if asso_points:
            shared_clause = f" et membre de {asso_points[0]} comme vous"
        elif exp_points:
            shared_clause = f" (nous sommes tous les deux passés par {exp_points[0]})"
        elif hops:
            shared_clause = f" ({hops[0].reason.lower()})"

        if first_hop.id == target.id:
            msg = (
                f"Bonjour {first_name}, je suis {student.full_name} ({promo_txt}){shared_clause}. "
                f"Je m'intéresse à votre parcours chez {target.current_company or 'votre entreprise'} "
                f"dans le cadre d'un projet ({intent}). Seriez-vous disponible 15 minutes pour échanger ? Merci beaucoup !"
            )
        else:
            next_name = hops[1].to_name if len(hops) > 1 else target.full_name
            msg = (
                f"Bonjour {first_name}, je suis {student.full_name} ({promo_txt}){shared_clause}. "
                f"Dans le cadre de ma recherche ({intent}), j'aimerais beaucoup échanger avec {target.full_name} "
                f"({target.current_company or target.current_role or 'alumni'}). "
                f"Accepteriez-vous de me mettre en relation avec {next_name} ? Merci beaucoup !"
            )
        if extra_context:
            msg = f"{msg} ({extra_context.strip()})"
        return _sanitize_outreach_text(msg, msg)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [deterministic_text_embedding(t, dim=self.embedding_dim) for t in texts]


class VertexLLMService:
    """Async wrapper around Google Cloud Vertex AI (Gemma 4 + gemini-embedding-2)."""

    def __init__(
        self,
        *,
        project: str,
        location: str,
        gemma_model: str,
        embedding_model: str,
        embedding_dim: int = 768,
    ) -> None:
        self.project = project
        self.location = location
        self.gemma_model = gemma_model
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self.client = genai.Client(vertexai=True, project=project, location=location)
        self._fallback = DeterministicLLMService(embedding_dim=embedding_dim)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _generate_sync(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        schema: Optional[type] = None,
    ) -> str:
        if schema is not None:
            try:
                res = self.client.models.generate_content(
                    model=self.gemma_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=temperature,
                    ),
                )
                return res.text or ""
            except Exception:
                # Vertex global endpoints for Gemma 4 may reject response_schema natively
                pass

        res = self.client.models.generate_content(
            model=self.gemma_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        return res.text or ""

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            response = self.client.models.embed_content(
                model=self.embedding_model,
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=self.embedding_dim),
            )
            vectors.append([float(v) for v in response.embeddings[0].values])
        return vectors

    async def parse_user_query(self, query: str) -> ParsedQuery:
        prompt = (
            "Analyse cette requête d'un étudiant de CentraleSupélec qui cherche un alumni et réponds "
            "UNIQUEMENT en JSON valide avec les clés exactes : "
            "target_sector (string ou null), target_companies (liste de strings), "
            "target_roles (liste de strings), worked_with (string ou null), "
            "icebreakers (liste de strings), intent (string), summary_label (string court), limit (int, défaut 3).\n\n"
            f"Requête : {query}"
        )
        try:
            raw = await asyncio.to_thread(self._generate_sync, prompt, temperature=0.1, schema=ParsedQuery)
            try:
                return ParsedQuery.model_validate_json(raw)
            except Exception:
                return ParsedQuery.model_validate(extract_json_fallback(raw))
        except Exception:
            return await self._fallback.parse_user_query(query)

    async def extract_profile_from_snippets(self, full_name: str, snippets: str) -> EnrichedProfile:
        if not snippets.strip():
            return EnrichedProfile()

        class _LLMExtractedProfile(BaseModel):
            bio: str = ""
            current_role: Optional[str] = None
            current_company: Optional[str] = None
            sector: Optional[str] = None
            location: Optional[str] = None
            linkedin_url: Optional[str] = None
            experiences: list[Experience] = Field(default_factory=list)
            associations: list[str] = Field(default_factory=list)
            passions: list[str] = Field(default_factory=list)

        prompt = (
            f"À partir UNIQUEMENT des extraits web ci-dessous concernant {full_name}, extrais les informations "
            "factuelles de cette personne précise. N'invente, ne devine et n'extrapole JAMAIS rien : si une "
            "information est absente ou incertaine, laisse null ou une liste vide.\n\n"
            f"Extraits web :\n{snippets}\n\n"
            "Règles strictes anti-hallucination :\n"
            f"- Vérifie pour chaque extrait qu'il concerne bien {full_name} (et pas un homonyme, une autre personne, "
            "ou un annuaire listant plusieurs profils). IGNORE complètement tout extrait ambigu ou concernant quelqu'un d'autre.\n"
            f"- Si aucun extrait ne concerne clairement {full_name}, renvoie bio='', tous les champs à null et toutes les listes vides.\n"
            "- bio : 1 à 2 phrases courtes et factuelles basées uniquement sur les extraits correspondants, sans URL ni markdown.\n"
            "- current_company : UNIQUEMENT le nom court de l'entreprise ou organisation actuelle (ex: 'Mistral AI', 'Doctolib'). "
            "INTERDICTION formelle d'y mettre 'CentraleSupélec', une école, ou un fragment de phrase.\n"
            "- experiences : uniquement les expériences professionnelles/stages explicitement mentionnées pour cette personne.\n"
            "- location : ville ou pays actuel si explicitement mentionné (sinon null).\n"
            "- linkedin_url : URL publique exacte de type https://.../linkedin.com/in/... appartenant à cette personne si présente dans les extraits (sinon null).\n"
            "- associations / passions : uniquement si explicitement mentionnés pour cette personne dans les extraits.\n\n"
            "Réponds uniquement en JSON valide avec les clés : "
            "bio (string), current_role (string ou null), current_company (string ou null), sector (string ou null), "
            "location (string ou null), linkedin_url (string ou null), "
            "experiences (liste de {company, role, start_date, end_date, period}), "
            "associations (liste de strings : UNIQUEMENT des associations étudiantes, clubs ou organismes bénévoles, PAS d'entreprises ni d'écoles), "
            "passions (liste de strings)."
        )
        try:
            raw = await asyncio.to_thread(
                self._generate_sync, prompt, temperature=0.0, schema=_LLMExtractedProfile
            )
            try:
                parsed = _LLMExtractedProfile.model_validate_json(raw)
            except Exception:
                parsed = _LLMExtractedProfile.model_validate(extract_json_fallback(raw))
            return EnrichedProfile(
                bio=parsed.bio,
                current_role=parsed.current_role,
                current_company=parsed.current_company,
                sector=parsed.sector,
                location=parsed.location,
                linkedin_url=parsed.linkedin_url,
                photo_url=None,
                experiences=parsed.experiences,
                associations=parsed.associations,
                passions=parsed.passions,
            )
        except Exception:
            return await self._fallback.extract_profile_from_snippets(full_name, snippets)

    async def generate_outreach_message(
        self,
        student: ProfileRecord,
        first_hop: ProfileRecord,
        target: ProfileRecord,
        hops: list[HopDetail],
        intent: str,
        common_points: list[str],
        extra_context: Optional[str] = None,
    ) -> str:
        fallback_msg = await self._fallback.generate_outreach_message(
            student, first_hop, target, hops, intent, common_points, extra_context
        )
        hop_summary = [
            {"from": h.from_name, "to": h.to_name, "probability": h.probability, "reason": h.reason}
            for h in hops
        ]
        common_txt = ", ".join(common_points) if common_points else "Réseau CentraleSupélec"
        extra_clause = f"\n- Précision demandée : {extra_context}" if extra_context else ""

        prompt = f"""Tu es un assistant carrière pour étudiants de CentraleSupélec.
Rédige un message LinkedIn court, naturel et chaleureux (maximum 80 mots) que {student.full_name}
va envoyer à {first_hop.full_name} ({first_hop.current_role or 'Alumni'} chez {first_hop.current_company or 'son entreprise'}).

Contexte strict :
- Lien direct entre l'étudiant et {first_hop.full_name} : {hops[0].reason if hops else 'Réseau CentraleSupélec'}
- Points communs VÉRIFIÉS (seuls autorisés à être cités) : {common_txt}
- Règle stricte anti-hallucination : ne cite AUCUN autre point commun, passion ou association que ceux listés ci-dessus.
- Objectif final : entrer en contact avec {target.full_name} ({target.current_role or 'Alumni'} chez {target.current_company or ''}) pour : {intent}.
- Chaîne complète : {json.dumps(hop_summary, ensure_ascii=False)}{extra_clause}

Ne mets AUCUN placeholder type [Nom] ou [Entreprise]. Écris directement le message prêt à envoyer en français."""

        try:
            raw = await asyncio.to_thread(self._generate_sync, prompt, temperature=0.4, schema=None)
            return _sanitize_outreach_text(raw, fallback_msg)
        except Exception:
            return fallback_msg

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            return await asyncio.to_thread(self._embed_sync, texts)
        except Exception:
            return await self._fallback.embed_texts(texts)
