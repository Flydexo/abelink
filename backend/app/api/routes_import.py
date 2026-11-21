"""LinkedIn archive import endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.auth import get_current_student_id
from app.db.repository import EdgeRecord, ProfileRecord
from app.schemas.import_linkedin import LinkedInImportSummary
from app.services.linkedin_parser import (
    build_profile_lookup_indexes,
    match_connection_to_profile,
    parse_linkedin_archive,
)

router = APIRouter(prefix="/api/v1/linkedin", tags=["linkedin"])


@router.post(
    "/import",
    response_model=LinkedInImportSummary,
    summary="Importer une archive LinkedIn (.zip ou Connections.csv)",
    description=(
        "Extrait Connections.csv, Positions.csv et Education.csv d'une archive officielle LinkedIn, "
        "crée ou met à jour le profil étudiant, crée les arêtes explicites (p=0.95) vers les alumni "
        "matchés et recalcule les arêtes inférées dans Postgres et NetworkX."
    ),
    operation_id="import_linkedin_archive",
)
async def import_linkedin(
    request: Request,
    file: UploadFile = File(..., description="Fichier .zip d'export LinkedIn ou Connections.csv."),
    full_name: Optional[str] = Form(default=None),
    email: Optional[str] = Form(default=None),
    promo_year: Optional[int] = Form(default=None),
    associations: Optional[str] = Form(default=None, description="Liste séparée par des virgules."),
    passions: Optional[str] = Form(default=None, description="Liste séparée par des virgules."),
    student_id: str = Depends(get_current_student_id),
) -> LinkedInImportSummary:
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide.")

    try:
        parsed = parse_linkedin_archive(raw_bytes, filename=file.filename or "archive.zip")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Impossible de lire l'archive LinkedIn : {exc}",
        ) from exc

    container = request.app.state.container
    repository = container.repository
    graph_engine = container.graph_engine
    llm = container.llm_service

    existing = await repository.get_profile(student_id)
    resolved_name = (
        full_name
        or parsed.full_name_inferred
        or (existing.full_name if existing else None)
        or "Étudiant CentraleSupélec"
    )
    resolved_email = email or (existing.email if existing else None)
    resolved_promo = promo_year or parsed.promo_year_inferred or (existing.promo_year if existing else None)

    merged_assos = list(existing.associations) if existing else []
    if associations:
        for item in associations.split(","):
            val = item.strip()
            if val and val not in merged_assos:
                merged_assos.append(val)

    merged_passions = list(existing.passions) if existing else []
    if passions:
        for item in passions.split(","):
            val = item.strip()
            if val and val not in merged_passions:
                merged_passions.append(val)

    exp_dicts = [e.model_dump() for e in parsed.experiences] or (list(existing.experiences) if existing else [])
    edu_dicts = [e.model_dump() for e in parsed.educations] or (list(existing.education) if existing else [])
    current_role = exp_dicts[0].get("role") if exp_dicts else (existing.current_role if existing else None)
    current_company = exp_dicts[0].get("company") if exp_dicts else (existing.current_company if existing else None)

    student_profile = ProfileRecord(
        id=student_id,
        full_name=resolved_name,
        email=resolved_email,
        linkedin_url=existing.linkedin_url if existing else None,
        promo_year=resolved_promo,
        current_role=current_role,
        current_company=current_company,
        sector=existing.sector if existing else None,
        location=existing.location if existing else None,
        bio=parsed.headline_inferred or (existing.bio if existing else None),
        experiences=exp_dicts,
        education=edu_dicts,
        associations=merged_assos,
        passions=merged_passions,
        is_student=True,
        has_imported_linkedin=True,
        enrichment_source="LINKEDIN_ARCHIVE",
        last_enriched_at=existing.last_enriched_at if existing else None,
        embedding=None,
    )
    student_profile.embedding = (await llm.embed_texts([student_profile.searchable_text()]))[0]
    await repository.upsert_profile(student_profile)

    all_profiles = await repository.list_profiles()
    other_profiles = [p for p in all_profiles if p.id != student_profile.id]
    by_url, by_name_company = build_profile_lookup_indexes(other_profiles)

    explicit_edges: list[EdgeRecord] = []
    matched_ids: set[str] = set()
    unmatched_sample: list[str] = []

    for conn in parsed.connections:
        matched = match_connection_to_profile(conn, by_url, by_name_company)
        if matched is None:
            if len(unmatched_sample) < 10:
                unmatched_sample.append(conn.full_name)
            continue
        if matched.id in matched_ids:
            continue
        matched_ids.add(matched.id)
        src, dst = (student_profile.id, matched.id) if student_profile.id < matched.id else (matched.id, student_profile.id)
        explicit_edges.append(
            EdgeRecord(
                source_id=src,
                target_id=dst,
                edge_type="EXPLICIT_LINKEDIN",
                probability=0.95,
                reason="Connexion LinkedIn directe",
            )
        )

    inferred_edges = graph_engine.infer_edges_for_profile(student_profile, other_profiles)
    all_new_edges = explicit_edges + inferred_edges
    if all_new_edges:
        await repository.upsert_edges(all_new_edges)

    graph_engine.upsert_node(student_profile)
    graph_engine.upsert_edges(all_new_edges)

    return LinkedInImportSummary(
        profile_id=student_profile.id,
        full_name=student_profile.full_name,
        connections_parsed=len(parsed.connections),
        profiles_matched=len(matched_ids),
        explicit_edges_created=len(explicit_edges),
        inferred_edges_created=len(inferred_edges),
        experiences_imported=len(parsed.experiences),
        educations_imported=len(parsed.educations),
        promo_year_inferred=resolved_promo,
        unmatched_sample=unmatched_sample,
    )
