"""Authentication helpers for web sessions (JWT), personal Bearer API tokens, and MCP context."""

from __future__ import annotations

import hashlib
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings
from app.db.repository import AbstractAlumniRepository

# Propagates HTTP Authorization Bearer token into FastMCP tool calls
mcp_bearer_token_ctx: ContextVar[Optional[str]] = ContextVar("mcp_bearer_token_ctx", default=None)


def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_api_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash)."""
    raw = f"abk_{secrets.token_hex(24)}"
    return raw, hash_api_token(raw)


def create_session_jwt(profile_id: str, settings: Settings, expires_hours: int = 24 * 7) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": profile_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
        "iss": "abelink",
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_session_jwt(token: str, settings: Settings) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.auth_secret, algorithms=["HS256"], issuer="abelink")
        sub = payload.get("sub")
        return str(sub) if sub else None
    except jwt.PyJWTError:
        return None


async def resolve_student_id_from_bearer(
    raw_token: Optional[str],
    repository: AbstractAlumniRepository,
    settings: Settings,
) -> Optional[str]:
    if not raw_token:
        return None
    token = raw_token.strip()
    if not token:
        return None

    if token.startswith("abk_"):
        return await repository.resolve_api_token(hash_api_token(token))

    jwt_sub = decode_session_jwt(token, settings)
    if jwt_sub:
        return jwt_sub

    # Fallback: try token lookup in case custom token format is stored hashed
    return await repository.resolve_api_token(hash_api_token(token))


async def resolve_student_id_for_mcp(
    user_email_or_id: Optional[str],
    repository: AbstractAlumniRepository,
    settings: Settings,
) -> str:
    bearer = mcp_bearer_token_ctx.get()
    if bearer:
        resolved = await resolve_student_id_from_bearer(bearer, repository, settings)
        if resolved:
            return resolved
        raise ValueError("Bearer token invalide ou révoqué pour MCP.")

    if user_email_or_id:
        profile = await repository.get_profile_by_email_or_id(user_email_or_id)
        if profile is not None:
            return profile.id
        raise ValueError(f"Profil utilisateur introuvable: {user_email_or_id}")

    if settings.allow_demo_auth:
        demo = await repository.get_profile(settings.default_demo_student_id)
        if demo is not None:
            return demo.id
        profiles = await repository.list_profiles()
        students = [p for p in profiles if p.is_student]
        if students:
            return students[0].id

    raise ValueError("Authentification requise : fournissez un Bearer Token ou user_email_or_id.")


def get_repository(request: Request) -> AbstractAlumniRepository:
    return request.app.state.container.repository


async def get_current_student_id(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_demo_user_id: Optional[str] = Header(default=None, alias="X-Demo-User-Id"),
    settings: Settings = Depends(get_settings),
) -> str:
    container = request.app.state.container
    repository: AbstractAlumniRepository = container.repository

    if authorization:
        scheme, _, creds = authorization.partition(" ")
        if scheme.lower() != "bearer" or not creds.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="En-tête Authorization Bearer invalide.",
            )
        resolved = await resolve_student_id_from_bearer(creds.strip(), repository, settings)
        if not resolved:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Jeton invalide ou expiré.",
            )
        return resolved

    if settings.allow_demo_auth:
        if x_demo_user_id:
            prof = await repository.get_profile_by_email_or_id(x_demo_user_id)
            if prof is not None:
                return prof.id
        demo = await repository.get_profile(settings.default_demo_student_id)
        if demo is not None:
            return demo.id
        profiles = await repository.list_profiles()
        students = [p for p in profiles if p.is_student]
        if students:
            return students[0].id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentification requise.",
    )


class MCPBearerMiddleware:
    """ASGI middleware capturing Authorization Bearer headers for the mounted FastMCP app."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        bearer: Optional[str] = None
        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                raw = value.decode("latin-1")
                scheme, _, creds = raw.partition(" ")
                if scheme.lower() == "bearer" and creds.strip():
                    bearer = creds.strip()
                break

        forwarded_scope = dict(scope)
        forwarded_scope["path"] = "/"
        forwarded_scope["raw_path"] = b"/"

        token = mcp_bearer_token_ctx.set(bearer)
        try:
            await self.app(forwarded_scope, receive, send)
        finally:
            mcp_bearer_token_ctx.reset(token)
