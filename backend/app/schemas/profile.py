"""Pydantic schemas for student/alumni profiles, enrichment, and API tokens."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Experience(BaseModel):
    company: str = Field(..., description="Nom de l'entreprise ou de l'organisation.", examples=["Mistral AI"])
    role: str = Field(..., description="Intitulé du poste ou rôle occupé.", examples=["Lead ML Engineer"])
    start_date: Optional[str] = Field(default=None, description="Date de début (ex: '2022-03' ou '2022').")
    end_date: Optional[str] = Field(default=None, description="Date de fin (ex: '2024-06' ou 'Present').")
    period: Optional[str] = Field(default=None, description="Période textuelle brute si les dates exactes manquent.", examples=["2022-2024"])


class Education(BaseModel):
    school: str = Field(..., description="Établissement d'enseignement.", examples=["CentraleSupélec"])
    degree: Optional[str] = Field(default=None, description="Diplôme ou cursus.", examples=["Diplôme d'ingénieur"])
    start_year: Optional[int] = Field(default=None, description="Année d'entrée.")
    end_year: Optional[int] = Field(default=None, description="Année de diplôme.")


class EnrichedProfile(BaseModel):
    bio: str = Field(default="", description="Résumé court et factuel du parcours professionnel.")
    current_role: Optional[str] = Field(default=None, description="Poste actuel le plus récent.")
    current_company: Optional[str] = Field(default=None, description="Entreprise actuelle la plus récente.")
    sector: Optional[str] = Field(default=None, description="Secteur d'activité principal.")
    location: Optional[str] = Field(default=None, description="Ville ou pays actuel.")
    linkedin_url: Optional[str] = Field(default=None, description="URL publique du profil LinkedIn.")
    photo_url: Optional[str] = Field(default=None, description="URL de la photo de profil LinkedIn.")
    experiences: list[Experience] = Field(default_factory=list)
    associations: list[str] = Field(
        default_factory=list,
        description="Uniquement des associations étudiantes, clubs ou organismes bénévoles (aucune entreprise ni école).",
    )
    passions: list[str] = Field(default_factory=list)


class ProfileSummary(BaseModel):
    id: str
    full_name: str
    promo_year: Optional[int] = None
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    sector: Optional[str] = None
    location: Optional[str] = None
    photo_url: Optional[str] = None
    short_meta: str = Field(default="", description="Résumé compact pour l'affichage graphe/UI.")


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    photo_url: Optional[str] = None
    promo_year: Optional[int] = None
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    sector: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    associations: list[str] = Field(default_factory=list)
    passions: list[str] = Field(default_factory=list)
    is_student: bool = False
    has_imported_linkedin: bool = False
    enrichment_source: str = "BASE_DB"
    last_enriched_at: Optional[datetime] = None


class TokenCreateRequest(BaseModel):
    label: str = Field(default="Claude / ChatGPT", max_length=80, description="Nom lisible du token personnel.")


class TokenCreateResponse(BaseModel):
    id: str
    label: str
    token: str = Field(..., description="Jeton Bearer en clair, affiché une seule fois.")
    created_at: datetime


class TokenListItem(BaseModel):
    id: str
    label: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
