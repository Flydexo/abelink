"""Pydantic schemas for LinkedIn ZIP/CSV archive imports."""

from typing import Optional

from pydantic import BaseModel, Field


class LinkedInImportSummary(BaseModel):
    profile_id: str = Field(..., description="Identifiant du profil étudiant mis à jour.")
    full_name: str
    connections_parsed: int = Field(..., ge=0)
    profiles_matched: int = Field(..., ge=0)
    explicit_edges_created: int = Field(..., ge=0)
    inferred_edges_created: int = Field(..., ge=0)
    experiences_imported: int = Field(..., ge=0)
    educations_imported: int = Field(..., ge=0)
    promo_year_inferred: Optional[int] = None
    unmatched_sample: list[str] = Field(default_factory=list)
