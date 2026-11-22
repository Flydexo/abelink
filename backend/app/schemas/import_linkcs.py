"""Summary of an administrative LinkCS JSON import."""

from typing import Literal

from pydantic import BaseModel, Field


class LinkCSImportSummary(BaseModel):
    records_received: int = Field(..., ge=0)
    profiles_added: int = Field(..., ge=0)
    profiles_skipped: int = Field(..., ge=0)
    relationships_added: int = Field(..., ge=0)
    storage: Literal["postgres", "in_memory"]
