"""Conversational Agent Chat REST & SSE streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.routes_search import _resolve_target_student_id
from app.auth import get_current_student_id
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Discuter avec l'agent réseau Abelink pour trouver des alumni et rédiger des introductions",
    operation_id="chat_alumni_agent",
)
async def chat_alumni_agent(
    payload: ChatRequest,
    request: Request,
    auth_student_id: str = Depends(get_current_student_id),
) -> ChatResponse:
    student_id = await _resolve_target_student_id(request, payload.user_id, auth_student_id)
    try:
        return await request.app.state.container.chat_agent.run_chat(student_id, payload.messages)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/chat/stream",
    summary="Discuter avec l'agent réseau Abelink en Server-Sent Events (SSE)",
    description=(
        "Émet les événements SSE successifs : assistant_intro -> tool_start/tool_done -> final_result."
    ),
    operation_id="stream_chat_alumni_agent",
)
async def stream_chat_alumni_agent(
    payload: ChatRequest,
    request: Request,
    auth_student_id: str = Depends(get_current_student_id),
) -> StreamingResponse:
    student_id = await _resolve_target_student_id(request, payload.user_id, auth_student_id)
    student = await request.app.state.container.repository.get_profile(student_id)
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profil étudiant introuvable: {student_id}",
        )

    queue: asyncio.Queue[Optional[tuple[str, dict[str, Any]]]] = asyncio.Queue()

    async def on_event(ev_name: str, data: dict[str, Any]) -> None:
        await queue.put((ev_name, data))

    async def runner() -> None:
        try:
            await request.app.state.container.chat_agent.run_chat(
                student_id,
                payload.messages,
                event_callback=on_event,
            )
        except Exception as exc:
            # Database exceptions can contain SQL and query parameters.
            logger.error("Chat stream failed (%s)", type(exc).__name__)
            await queue.put(("error", {"detail": "La recherche a échoué. Veuillez réessayer."}))
        finally:
            await queue.put(None)

    async def event_stream() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                ev_name, data = item
                data_json = json.dumps(data, ensure_ascii=False)
                yield f"event: {ev_name}\ndata: {data_json}\n\n"
            await task
        except asyncio.CancelledError:
            task.cancel()
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
