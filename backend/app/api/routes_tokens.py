"""Personal Bearer token management endpoints for Claude MCP and ChatGPT Actions."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import generate_api_token, get_current_student_id
from app.schemas.profile import TokenCreateRequest, TokenCreateResponse, TokenListItem

router = APIRouter(prefix="/api/v1/tokens", tags=["tokens"])


@router.post(
    "",
    response_model=TokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un token Bearer personnel pour Claude (MCP) ou ChatGPT (Actions)",
    operation_id="create_api_token",
)
async def create_token(
    payload: TokenCreateRequest,
    request: Request,
    student_id: str = Depends(get_current_student_id),
) -> TokenCreateResponse:
    raw_token, token_hash = generate_api_token()
    record = await request.app.state.container.repository.create_api_token(
        profile_id=student_id,
        token_hash=token_hash,
        label=payload.label,
    )
    return TokenCreateResponse(
        id=record.id,
        label=record.label,
        token=raw_token,
        created_at=record.created_at,
    )


@router.get(
    "",
    response_model=list[TokenListItem],
    summary="Lister les tokens Bearer actifs de l'étudiant connecté",
    operation_id="list_api_tokens",
)
async def list_tokens(
    request: Request,
    student_id: str = Depends(get_current_student_id),
) -> list[TokenListItem]:
    records = await request.app.state.container.repository.list_api_tokens(student_id)
    return [
        TokenListItem(
            id=r.id,
            label=r.label,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
        )
        for r in records
    ]


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Révoquer un token Bearer personnel",
    operation_id="revoke_api_token",
)
async def delete_token(
    token_id: str,
    request: Request,
    student_id: str = Depends(get_current_student_id),
) -> None:
    deleted = await request.app.state.container.repository.delete_api_token(token_id, student_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token introuvable.")
