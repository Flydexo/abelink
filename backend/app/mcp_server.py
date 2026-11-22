"""MCP server (mcp 2.x MCPServer) exposing Abelink alumni search, alternative paths, and outreach drafting for Claude."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from mcp.server.mcpserver import MCPServer

from app.auth import resolve_student_id_for_mcp
from app.schemas.search import ActionPlanRequest

if TYPE_CHECKING:
    from app.main import AppContainer


def create_mcp_server(container_getter: Any) -> MCPServer:
    """Create an MCPServer instance bound dynamically to the FastAPI AppContainer."""
    mcp = MCPServer(name="Abelink Alumni Graph")

    @mcp.tool()
    async def search_alumni_action_plan(
        query: str,
        user_email_or_id: Optional[str] = None,
        limit: int = 3,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Recherche les alumni pertinents et calcule les chemins d'introduction optimaux + messages d'accroche.

        Utilise le pipeline complet (parsing LLM -> pré-filtre hybride SQL/pgvector ->
        enrichissement Tavily si nécessaire -> Dijkstra -ln(p) -> message au premier maillon).
        """
        container: AppContainer = container_getter()
        student_id = await resolve_student_id_for_mcp(
            user_email_or_id,
            container.repository,
            container.settings,
        )
        res = await container.search_agent.run_action_plan(
            student_id,
            ActionPlanRequest(query=query, limit=limit, offset=offset),
        )
        return res.model_dump(mode="json")

    @mcp.tool()
    async def get_more_connections(
        target_id: str,
        user_email_or_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Retourne les chemins alternatifs vers un alumni cible et la fiche détaillée des maillons."""
        container: AppContainer = container_getter()
        student_id = await resolve_student_id_for_mcp(
            user_email_or_id,
            container.repository,
            container.settings,
        )
        target = await container.repository.get_profile_by_email_or_id(target_id)
        if target is None:
            raise ValueError(f"Profil cible introuvable: {target_id}")

        paths = container.graph_engine.find_connection_paths(
            student_id,
            target.id,
            max_hops=4,
            k_paths=5,
        )
        hop_ids: list[str] = []
        for path in paths:
            for hop in path.hops:
                for nid in (hop.to_id, hop.from_id):
                    if nid != student_id and nid not in hop_ids:
                        hop_ids.append(nid)

        hop_profiles: dict[str, Any] = {}
        for hid in hop_ids:
            prof = await container.repository.get_profile(hid)
            if prof is not None:
                hop_profiles[hid] = prof.to_profile_read().model_dump(mode="json")

        return {
            "student_id": student_id,
            "target": target.to_profile_read().model_dump(mode="json"),
            "paths": [p.model_dump(mode="json") for p in paths],
            "hop_profiles": hop_profiles,
        }

    @mcp.tool()
    async def draft_outreach_message(
        first_hop_id: str,
        target_id: str,
        context: str = "",
        user_email_or_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Rédige ou adapte un message d'approche adressé à un premier maillon précis pour joindre une cible."""
        container: AppContainer = container_getter()
        student_id = await resolve_student_id_for_mcp(
            user_email_or_id,
            container.repository,
            container.settings,
        )
        return await container.search_agent.draft_custom_outreach(
            student_id=student_id,
            first_hop_id=first_hop_id,
            target_id=target_id,
            context=context,
        )

    return mcp
