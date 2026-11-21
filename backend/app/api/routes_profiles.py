"""Profile directory & details endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.auth import get_current_student_id
from app.db.repository import _normalize_text
from app.schemas.profile import ProfileRead, ProfileSummary

router = APIRouter(prefix="/api/v1", tags=["profiles"])


@router.get(
    "/profiles",
    response_model=list[ProfileSummary],
    summary="Rechercher dans l'annuaire des profils (étudiants et alumni)",
    operation_id="search_profiles_directory",
)
async def list_directory_profiles(
    request: Request,
    q: str = Query(default="", description="Filtre texte (nom, email, entreprise ou association)."),
    limit: int = Query(default=15, ge=1, le=50),
    _: str = Depends(get_current_student_id),
) -> list[ProfileSummary]:
    profiles = await request.app.state.container.repository.list_profiles()
    needle = _normalize_text(q)

    matched = []
    for prof in profiles:
        if needle:
            haystack = _normalize_text(
                " ".join(
                    [
                        prof.full_name,
                        prof.email or "",
                        prof.current_company or "",
                        " ".join(prof.associations),
                    ]
                )
            )
            if needle not in haystack:
                continue
        matched.append(prof)

    # Put student profiles and exact prefix matches first
    if needle:
        matched.sort(key=lambda p: (0 if _normalize_text(p.full_name).startswith(needle) else 1, not p.is_student, p.full_name))
    else:
        matched.sort(key=lambda p: (not p.is_student, p.full_name))

    return [p.to_profile_summary() for p in matched[:limit]]


@router.get(
    "/me",
    response_model=ProfileRead,
    summary="Récupérer le profil complet de l'étudiant authentifié",
    operation_id="get_current_student_profile",
)
async def get_me(
    request: Request,
    student_id: str = Depends(get_current_student_id),
) -> ProfileRead:
    profile = await request.app.state.container.repository.get_profile(student_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profil étudiant introuvable.")
    return profile.to_profile_read()


@router.get(
    "/profiles/{profile_id}",
    response_model=ProfileRead,
    summary="Obtenir la fiche détaillée d'un alumni ou d'un maillon",
    description=(
        "Retourne toutes les informations structurées d'un profil (expériences, associations, passions, bio) "
        "pour vérifier les points communs réels avant de rédiger un message."
    ),
    operation_id="get_profile_details",
)
async def get_profile(
    profile_id: str,
    request: Request,
    _: str = Depends(get_current_student_id),
) -> ProfileRead:
    profile = await request.app.state.container.repository.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profil introuvable.")
    return profile.to_profile_read()
