"""Administrative JSON import, independent of demo identities and user bootstrap."""

import asyncio
import json
import secrets

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from sqlalchemy.exc import IntegrityError

from app.db.repository import EdgeRecord, PostgresAlumniRepository
from app.schemas.import_linkcs import LinkCSImportSummary
from app.services.linkcs_loader import load_linkcs_rows
from app.services.linkedin_parser import normalize_linkedin_url

router = APIRouter(prefix="/api/v1/linkcs", tags=["linkcs"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 5000
MAX_RELATIONSHIPS = 100_000


async def require_import_key(
    request: Request,
    provided_key: str | None = Header(default=None, alias="X-LinkCS-Import-Token"),
) -> None:
    if request.app.state.container.settings.allow_public_access:
        return
    check_import_key(request.app.state.container.settings.linkcs_import_token, provided_key)


def check_import_key(expected_key: str | None, provided_key: str | None) -> None:
    if not expected_key:
        raise HTTPException(503, "Import LinkCS désactivé : configurez LINKCS_IMPORT_TOKEN sur le backend.")
    if not provided_key or not secrets.compare_digest(provided_key.encode(), expected_key.encode()):
        raise HTTPException(401, "Clé d’administration LinkCS absente ou invalide.")


@router.post("/import", response_model=LinkCSImportSummary, dependencies=[Depends(require_import_key)])
async def import_linkcs(
    request: Request,
    file: UploadFile = File(...),
    confirmed: bool = Form(False),
) -> LinkCSImportSummary:
    if not confirmed:
        raise HTTPException(400, "Confirmez que vous êtes autorisé à importer ces données.")
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(400, "Sélectionnez un dump LinkCS au format .json.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Le fichier dépasse la limite de 10 Mio.")
    try:
        rows = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise HTTPException(400, "Le fichier doit contenir du JSON UTF-8 valide.") from None
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise HTTPException(400, "Le dump doit être une liste non vide d’objets LinkCS.")
    if len(rows) > MAX_RECORDS:
        raise HTTPException(413, "Le dump dépasse la limite de 5 000 entrées.")
    for index, row in enumerate(rows, start=1):
        if any(not isinstance(row.get(key) or "", str) for key in ("nom_complet", "prenom", "nom", "login")):
            raise HTTPException(400, f"Ligne {index} : les noms et le login doivent être du texte.")
        if not (str(row.get("nom_complet") or "").strip() or str(row.get("prenom") or "").strip() or str(row.get("nom") or "").strip()):
            raise HTTPException(400, f"Ligne {index} : nom du profil manquant.")
    try:
        profiles, edges = await asyncio.to_thread(
            load_linkcs_rows, rows, include_demo_student=False, compute_embeddings=False,
            max_edges=MAX_RELATIONSHIPS,
        )
    except (ValueError, TypeError):
        raise HTTPException(400, "Dump LinkCS incompatible ou trop de relations ; vérifiez les champs et réduisez le fichier.") from None

    container = request.app.state.container
    existing = await container.repository.list_profiles()
    by_id = {profile.id: profile for profile in existing}
    by_url = {
        url: profile
        for profile in existing
        if (url := normalize_linkedin_url(profile.linkedin_url))
    }
    remapped_ids: dict[str, str] = {}
    additions = []
    for profile in profiles:
        matched = by_id.get(profile.id) or by_url.get(normalize_linkedin_url(profile.linkedin_url))
        if matched is not None:
            remapped_ids[profile.id] = matched.id
        else:
            additions.append(profile)
    mapped_edges: dict[tuple[str, str, str], EdgeRecord] = {}
    for edge in edges:
        source_id = remapped_ids.get(edge.source_id, edge.source_id)
        target_id = remapped_ids.get(edge.target_id, edge.target_id)
        if source_id == target_id:
            continue
        source_id, target_id = sorted((source_id, target_id))
        mapped = EdgeRecord(
            source_id=source_id, target_id=target_id, edge_type=edge.edge_type,
            probability=edge.probability, reason=edge.reason,
        )
        key = (source_id, target_id, edge.edge_type)
        if key not in mapped_edges or mapped.probability > mapped_edges[key].probability:
            mapped_edges[key] = mapped
    try:
        profiles_added, relationships_added = await container.repository.import_linkcs_records(
            additions, list(mapped_edges.values()),
        )
    except (IntegrityError, ValueError):
        raise HTTPException(409, "Conflit d’import : aucune modification appliquée ; réessayez avec les données à jour.") from None
    await container.graph_engine.reload_from_repository(container.repository)
    return LinkCSImportSummary(
        records_received=len(rows), profiles_added=profiles_added,
        profiles_skipped=len(rows) - profiles_added, relationships_added=relationships_added,
        storage="postgres" if isinstance(container.repository, PostgresAlumniRepository) else "in_memory",
    )
