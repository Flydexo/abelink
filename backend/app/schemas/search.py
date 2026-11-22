"""Pydantic schemas for hybrid search, graph pathfinding, action plans, and SSE events."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.profile import ProfileSummary


class ParsedQuery(BaseModel):
    target_sector: Optional[str] = Field(
        default=None,
        description="Secteur visé (ex: 'Énergie', 'Intelligence Artificielle', 'Santé / Tech').",
    )
    target_companies: list[str] = Field(
        default_factory=list,
        description="Entreprises explicitement demandées ou pertinentes pour la requête.",
    )
    target_roles: list[str] = Field(
        default_factory=list,
        description="Postes ou métiers visés (ex: 'Product Manager', 'Quant', 'ML Engineer').",
    )
    worked_with: Optional[str] = Field(
        default=None,
        description="Personne ou entreprise avec laquelle l'alumni cible a travaillé.",
    )
    icebreakers: list[str] = Field(
        default_factory=list,
        description="Passions, clubs, associations ou points communs recherchés.",
    )
    intent: str = Field(
        default="conseil carrière",
        description="Intention principale (stage de césure, échange métier, mentorat, entrepreneuriat).",
    )
    summary_label: str = Field(
        default="",
        description="Libellé court de la requête analysée pour l'UI.",
    )
    limit: int = Field(default=3, ge=1, le=10)


class SearchFilters(BaseModel):
    sector: Optional[str] = Field(default=None, description="Filtre secteur optionnel.")
    companies: list[str] = Field(default_factory=list, description="Filtre entreprises optionnel.")
    roles: list[str] = Field(default_factory=list, description="Filtre intitulés de poste optionnel.")
    worked_with: Optional[str] = Field(default=None, description="Filtre ancien collègue ou entreprise commune.")
    icebreakers: list[str] = Field(default_factory=list, description="Points communs ou passions souhaités.")
    promo_min: Optional[int] = Field(default=None, ge=1950, le=2035)
    promo_max: Optional[int] = Field(default=None, ge=1950, le=2035)


class ActionPlanRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=3,
        description="Requête en langage naturel de l'étudiant (ex: 'Je cherche un stage de césure dans l'énergie').",
        examples=["Je cherche un stage de césure dans une boîte qui travaille dans l'énergie"],
    )
    user_id: Optional[str] = Field(
        default=None,
        description="UUID ou email de l'étudiant connecté (optionnel si authentifié via Bearer Token).",
    )
    filters: Optional[SearchFilters] = Field(
        default=None,
        description="Filtres structurés optionnels complétant le parsing LLM.",
    )
    limit: int = Field(default=3, ge=1, le=10, description="Nombre de solutions alumni retournées.")
    offset: int = Field(default=0, ge=0, description="Décalage pour paginer vers les solutions suivantes.")


class HopDetail(BaseModel):
    from_id: str
    from_name: str
    from_meta: str
    to_id: str
    to_name: str
    to_meta: str
    probability: float = Field(..., ge=0.0, le=1.0)
    edge_type: str
    reason: str
    secondary_reasons: list[str] = Field(default_factory=list)


class ConnectionPath(BaseModel):
    total_probability: float = Field(..., ge=0.0, le=1.0)
    hop_count: int = Field(..., ge=1)
    hops: list[HopDetail]
    summary_label: str = ""


class ActionStep(BaseModel):
    when: str = Field(..., examples=["Aujourd'hui"])
    text: str


class ScoreBreakdown(BaseModel):
    profile_relevance: float = Field(..., ge=0.0, le=1.0)
    path_probability: float = Field(..., ge=0.0, le=1.0)
    common_points_score: float = Field(..., ge=0.0, le=1.0)
    total_score: float = Field(..., ge=0.0, le=1.0)


class AlumniSolution(BaseModel):
    target: ProfileSummary
    primary_path: Optional[ConnectionPath] = None
    alternative_paths: list[ConnectionPath] = Field(default_factory=list)
    icebreakers: list[str] = Field(default_factory=list)
    action_plan: list[ActionStep] = Field(default_factory=list)
    outreach_message: str
    first_hop: Optional[ProfileSummary] = None
    score_breakdown: ScoreBreakdown


class ActionPlanResponse(BaseModel):
    query: str
    parsed_query: ParsedQuery
    student_id: str
    candidates_scanned: int
    candidates_enriched: int
    companies_matched: list[str] = Field(default_factory=list)
    summary: str
    solutions: list[AlumniSolution] = Field(default_factory=list)
    offset: int = 0
    limit: int = 3
    total_candidates: int = 0


class GraphNode(BaseModel):
    id: str
    label: str
    meta: str = ""
    kind: Literal["student", "hop", "target"] = "hop"
    promo_year: Optional[int] = None
    company: Optional[str] = None
    role: Optional[str] = None
    photo_url: Optional[str] = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    probability: float
    reason: str
    secondary_reasons: list[str] = Field(default_factory=list)
    is_primary: bool = False


class GraphPathResponse(BaseModel):
    source_id: str
    target_id: str
    paths: list[ConnectionPath] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class SSEEvent(BaseModel):
    event: Literal["parsing", "hybrid_search", "enrichment", "pathfinding", "final_result"]
    title: str
    status: Literal["running", "done"] = "done"
    detail: str = ""
    chips: list[str] = Field(default_factory=list)
    data: Optional[dict[str, Any]] = None


class DraftMessageRequest(BaseModel):
    first_hop_id: str = Field(..., description="UUID du premier maillon destinataire du message.")
    target_id: str = Field(..., description="UUID de l'alumni cible final.")
    context: str = Field(default="", description="Consigne ou contexte supplémentaire (ton, stage, précision).")
    user_id: Optional[str] = Field(default=None, description="UUID, email ou nom de l'étudiant actif.")


class DraftMessageResponse(BaseModel):
    first_hop_id: str
    first_hop_name: str
    target_id: str
    target_name: str
    verified_common_points: str
    message: str
