"""Pydantic schemas for conversational Happenstance-style Agent Chat and SSE tool traces."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    user_id: Optional[str] = Field(
        default=None,
        description="UUID, email ou nom de l'étudiant actif.",
    )


class ToolCallTrace(BaseModel):
    id: str
    tool: str
    label: str
    detail: str = ""
    status: Literal["running", "done"] = "done"
    duration_ms: int = 0
    count: Optional[int] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""


class MutualContact(BaseModel):
    id: str
    full_name: str
    short_meta: str = ""
    reason: str = ""
    probability: float = 0.0
    photo_url: Optional[str] = None


class ChatPersonResult(BaseModel):
    id: str
    full_name: str
    role_company: str = ""
    location: Optional[str] = None
    thinking: str = ""
    source_url: Optional[str] = None
    source_label: Optional[str] = None
    photo_url: Optional[str] = None
    mutuals: list[MutualContact] = Field(default_factory=list)
    hop_count: Optional[int] = None


class ChatResponse(BaseModel):
    intro_text: str
    outro_text: str = ""
    tools_used: list[ToolCallTrace] = Field(default_factory=list)
    total_duration_ms: int = 0
    total_candidates: int = 0
    people: list[ChatPersonResult] = Field(default_factory=list)
    drafted_message: Optional[str] = None
