"""Search action-plan (REST + SSE) and graph path visualization endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.auth import get_current_student_id
from app.schemas.search import (
    ActionPlanRequest,
    ActionPlanResponse,
    DraftMessageRequest,
    DraftMessageResponse,
    GraphPathResponse,
    SSEEvent,
)

router = APIRouter(prefix="/api/v1", tags=["search"])


async def _resolve_target_student_id(
    request: Request,
    requested_user_id: Optional[str],
    auth_student_id: str,
) -> str:
    if not requested_user_id:
        return auth_student_id
    prof = await request.app.state.container.repository.get_profile_by_email_or_id(requested_user_id)
    if prof is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profil étudiant introuvable: {requested_user_id}",
        )
    return prof.id


@router.post(
    "/search/action-plan",
    response_model=ActionPlanResponse,
    summary="Rechercher des alumni et générer le plan d'action relationnel complet",
    description=(
        "Méta-endpoint principal (à appeler en UNE SEULE requête depuis ChatGPT Actions). "
        "Exécute les 4 étapes déterministes : (1) parsing structuré de la requête, "
        "(2) pré-filtre hybride SQL + pgvector (sans exclure les profils incomplets), "
        "(3) enrichissement web Just-In-Time (Tavily + Gemma 4) avec cache persistant, "
        "(4) calcul des meilleurs chemins probabilistes NetworkX (Dijkstra -ln(p)), "
        "points communs vérifiés, plan d'action en 3 étapes et message d'accroche adressé au premier maillon."
    ),
    operation_id="recommend_alumni_action_plan",
)
async def search_action_plan(
    payload: ActionPlanRequest,
    request: Request,
    auth_student_id: str = Depends(get_current_student_id),
) -> ActionPlanResponse:
    student_id = await _resolve_target_student_id(request, payload.user_id, auth_student_id)
    try:
        return await request.app.state.container.search_agent.run_action_plan(student_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/search/action-plan/stream",
    summary="Rechercher des alumni avec progression temps réel en Server-Sent Events (SSE)",
    description=(
        "Émet les événements temps réel successifs pour l'interface web : "
        "parsing -> hybrid_search -> enrichment -> pathfinding -> final_result."
    ),
    operation_id="stream_alumni_action_plan",
)
async def stream_action_plan(
    payload: ActionPlanRequest,
    request: Request,
    auth_student_id: str = Depends(get_current_student_id),
) -> StreamingResponse:
    student_id = await _resolve_target_student_id(request, payload.user_id, auth_student_id)
    queue: asyncio.Queue[Optional[SSEEvent]] = asyncio.Queue()

    async def on_event(ev: SSEEvent) -> None:
        await queue.put(ev)

    async def runner() -> None:
        try:
            await request.app.state.container.search_agent.run_action_plan(
                student_id,
                payload,
                event_callback=on_event,
            )
        finally:
            await queue.put(None)

    async def event_stream() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                data_json = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                yield f"event: {item.event}\ndata: {data_json}\n\n"
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


@router.get(
    "/graph/path",
    response_model=GraphPathResponse,
    summary="Calculer et retourner le graphe relationnel entre un étudiant et un alumni cible",
    description=(
        "Interroge le graphe NetworkX en mémoire pour retourner les chemins probabilistes optimaux "
        "ainsi que les listes `nodes` et `edges` prêtes pour React Flow ou react-force-graph."
    ),
    operation_id="get_connection_graph_path",
)
async def get_graph_path(
    request: Request,
    target_id: str = Query(..., description="UUID du profil alumni cible."),
    source_id: Optional[str] = Query(default=None, description="UUID source (défaut : étudiant connecté)."),
    max_hops: int = Query(default=4, ge=1, le=6),
    k_paths: int = Query(default=3, ge=1, le=6),
    auth_student_id: str = Depends(get_current_student_id),
) -> GraphPathResponse:
    container = request.app.state.container
    resolved_source = await _resolve_target_student_id(request, source_id, auth_student_id)

    target_profile = await container.repository.get_profile_by_email_or_id(target_id)
    if target_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profil cible introuvable.")

    paths = container.graph_engine.find_connection_paths(
        resolved_source,
        target_profile.id,
        max_hops=max_hops,
        k_paths=k_paths,
    )
    nodes, edges = container.graph_engine.get_subgraph_for_paths(
        resolved_source,
        target_profile.id,
        paths,
    )
    return GraphPathResponse(
        source_id=resolved_source,
        target_id=target_profile.id,
        paths=paths,
        nodes=nodes,
        edges=edges,
    )


@router.post(
    "/search/draft-message",
    response_model=DraftMessageResponse,
    summary="Adapter ou régénérer le message d'accroche pour un premier maillon donné",
    operation_id="draft_outreach_message_rest",
)
async def draft_message_endpoint(
    payload: DraftMessageRequest,
    request: Request,
    auth_student_id: str = Depends(get_current_student_id),
) -> DraftMessageResponse:
    student_id = await _resolve_target_student_id(request, payload.user_id, auth_student_id)
    try:
        result = await request.app.state.container.search_agent.draft_custom_outreach(
            student_id=student_id,
            first_hop_id=payload.first_hop_id,
            target_id=payload.target_id,
            context=payload.context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DraftMessageResponse(**result)
