"""Administrative, chunked import of Abelink database exports."""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from io import TextIOWrapper
from tempfile import TemporaryFile
from typing import BinaryIO
from uuid import uuid4

from anyio import to_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import DataError, IntegrityError
from starlette.requests import ClientDisconnect

from app.api.routes_linkcs import check_import_key
from app.db.repository import PostgresAlumniRepository
from app.schemas.import_linkcs import LinkCSImportSummary
from app.services.bundle_reader import BundleError, BundleReader

MAX_BYTES = 1024 * 1024 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
IDLE_SECONDS = 15 * 60
logger = logging.getLogger(__name__)


@dataclass
class Upload:
    id: str
    size: int
    file: BinaryIO
    received: int = 0
    expiry: asyncio.TimerHandle | None = None


class BundleUploads:
    def __init__(self):
        self.upload: Upload | None = None
        self.task: asyncio.Task | None = None
        self.results: deque[tuple[str, dict]] = deque(maxlen=16)
        self.lock = asyncio.Lock()

    def discard(self) -> None:
        if self.upload is not None:
            if self.upload.expiry is not None:
                self.upload.expiry.cancel()
            self.upload.file.close()
            self.upload = None

    def defer_expiry(self, upload: Upload) -> None:
        if upload.expiry is not None:
            upload.expiry.cancel()
        upload.expiry = asyncio.get_running_loop().call_later(IDLE_SECONDS, self.discard)

    def get(self, upload_id: str) -> Upload:
        if self.upload is None or self.upload.id != upload_id:
            raise HTTPException(404, "Cet import a expiré ou n’existe pas.")
        return self.upload

    async def run(self, upload: Upload, container) -> None:
        try:
            with TextIOWrapper(upload.file, encoding="utf-8-sig", newline="") as stream:
                received, added, edges = await container.repository.import_bundle_records(BundleReader(stream).records())
        except BundleError as exc:
            result = {"state": "failed", "detail": str(exc)}
        except (IntegrityError, DataError):
            result = {"state": "failed", "detail": "Conflit ou donnée invalide (URL LinkedIn, identifiant ou profil lié). Aucune modification appliquée."}
        except Exception as exc:
            logger.error("Bundle database import failed (%s)", type(exc).__name__)
            result = {"state": "failed", "detail": "L’import de l’export Abelink a échoué."}
        else:
            summary = LinkCSImportSummary(
                records_received=received, profiles_added=added, profiles_skipped=received - added,
                relationships_added=edges, storage="postgres",
            )
            result = {"state": "completed", "summary": summary.model_dump()}
            try:
                await container.graph_engine.reload_from_repository(container.repository)
            except Exception as exc:
                logger.error("Graph refresh after bundle import failed (%s)", type(exc).__name__)
                result["warning"] = "Données enregistrées, mais le graphe n’a pas pu être actualisé."
        finally:
            self.discard()
            self.task = None
        self.results.append((upload.id, result))

    async def close(self) -> None:
        if self.task is not None:
            await self.task
        self.discard()


async def require_bundle_key(
    request: Request,
    provided_key: str | None = Header(default=None, alias="X-LinkCS-Import-Token"),
) -> None:
    check_import_key(request.app.state.container.settings.linkcs_import_token, provided_key)


router = APIRouter(prefix="/api/v1/linkcs/bundle", tags=["linkcs"], dependencies=[Depends(require_bundle_key)])


@router.post("", status_code=201)
async def start_upload(request: Request, size: int = Query(gt=0), confirmed: bool = Query(False)) -> dict:
    container = request.app.state.container
    if not confirmed:
        raise HTTPException(400, "Confirmez que vous êtes autorisé à importer ces données.")
    if not isinstance(container.repository, PostgresAlumniRepository):
        raise HTTPException(503, "L’import d’un export Abelink nécessite PostgreSQL.")
    if size > MAX_BYTES:
        raise HTTPException(413, "L’export Abelink dépasse 1 Gio.")
    uploads: BundleUploads = request.app.state.bundle_uploads
    async with uploads.lock:
        if uploads.upload is not None:
            raise HTTPException(409, "Un import Abelink est déjà en cours.")
        try:
            file = TemporaryFile(dir=container.settings.bundle_upload_directory)
        except OSError:
            raise HTTPException(503, "Espace temporaire indisponible pour cette importation.") from None
        upload = uploads.upload = Upload(uuid4().hex, size, file)
        uploads.defer_expiry(upload)
    return {"id": upload.id, "chunk_size": CHUNK_BYTES}


@router.put("/{upload_id}")
async def upload_chunk(upload_id: str, offset: int, request: Request) -> dict:
    uploads: BundleUploads = request.app.state.bundle_uploads
    async with uploads.lock:
        upload = uploads.get(upload_id)
        if uploads.task is not None or offset != upload.received or offset >= upload.size:
            raise HTTPException(409, "Position de transfert incorrecte.")
        expected = min(CHUNK_BYTES, upload.size - offset)
        if request.headers.get("content-length", str(expected)) != str(expected):
            raise HTTPException(400, "Taille de bloc incorrecte.")
        uploads.defer_expiry(upload)
        payload = bytearray()
        try:
            async with asyncio.timeout(120):
                async for part in request.stream():
                    if len(payload) + len(part) > expected:
                        raise HTTPException(413, "Bloc de transfert trop volumineux.")
                    payload.extend(part)
        except (TimeoutError, ClientDisconnect):
            raise HTTPException(408, "Transfert du bloc interrompu.") from None
        if len(payload) != expected:
            raise HTTPException(400, "Bloc de transfert incomplet.")
        try:
            await to_thread.run_sync(upload.file.write, payload)
        except OSError:
            uploads.discard()
            raise HTTPException(507, "Espace insuffisant pour stocker temporairement l’export.") from None
        upload.received += expected
        return {"received": upload.received}


@router.post("/{upload_id}/finish", status_code=202)
async def finish_upload(upload_id: str, request: Request) -> dict:
    uploads: BundleUploads = request.app.state.bundle_uploads
    async with uploads.lock:
        upload = uploads.get(upload_id)
        if upload.received != upload.size:
            raise HTTPException(409, "Le transfert du fichier n’est pas terminé.")
        if uploads.task is None:
            try:
                await to_thread.run_sync(upload.file.seek, 0)
            except OSError:
                uploads.discard()
                raise HTTPException(507, "Impossible de lire le fichier temporaire.") from None
            upload.expiry.cancel()
            uploads.task = asyncio.create_task(uploads.run(upload, request.app.state.container))
    return {"state": "importing"}


@router.get("/{upload_id}")
async def upload_status(upload_id: str, request: Request) -> dict:
    uploads: BundleUploads = request.app.state.bundle_uploads
    for completed_id, result in uploads.results:
        if completed_id == upload_id:
            return result
    upload = uploads.get(upload_id)
    return {"state": "importing" if uploads.task is not None else "uploading", "received": upload.received}


@router.delete("/{upload_id}", status_code=204)
async def discard_upload(upload_id: str, request: Request) -> None:
    uploads: BundleUploads = request.app.state.bundle_uploads
    async with uploads.lock:
        uploads.get(upload_id)
        if uploads.task is not None:
            raise HTTPException(409, "Le traitement de cet import a déjà commencé.")
        uploads.discard()
