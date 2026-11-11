"""Authentication for every request.

User requests: the Next.js server signs a 5-minute token (aud=foxhood-api) carrying the user's Google
account id (sub), email and name. We verify it, then check the database: the email must hold an active
invite, and the Google account must match the one first linked to that email. The user row is created
on first sign-in. Revoking an invite takes effect on the very next request.

Service requests: Next.js asks "may this person sign in?" with a token for aud=foxhood-internal."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from db.repo import AdminRepo, normalize_email
from db.session import get_session

USER_AUDIENCE = "foxhood-api"
INTERNAL_AUDIENCE = "foxhood-internal"
ISSUER = "foxhood-web"


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    name: str | None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized("Missing bearer token")
    return authorization.removeprefix("Bearer ")


def _decode(token: str, audience: str) -> dict:
    try:
        return jwt.decode(token, settings.api_jwt_secret, algorithms=["HS256"], audience=audience,
                          issuer=ISSUER, options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError:
        raise _unauthorized("Invalid or expired token") from None


async def check_sign_in(session: AsyncSession, email: str, google_sub: str) -> tuple[bool, str]:
    """The single source of truth for 'may this person in?', used at sign-in AND on every request."""
    admin = AdminRepo(session)
    if not await admin.is_invited(email):
        return False, "not_invited"
    user = await admin.find_user(email)
    if user is not None and user.google_sub and user.google_sub != google_sub:
        return False, "account_mismatch"
    return True, "ok"


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    claims = _decode(_bearer(authorization), USER_AUDIENCE)
    try:
        email = normalize_email(str(claims.get("email", "")))
    except ValueError:
        raise _unauthorized("Token has no valid email") from None
    google_sub = str(claims["sub"])

    allowed, reason = await check_sign_in(session, email, google_sub)
    if not allowed:
        detail = "Not on the invite list" if reason == "not_invited" else "This email is linked to a different account"
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)

    user = await AdminRepo(session).record_login(email, google_sub)
    return CurrentUser(id=user.id, email=user.email, name=claims.get("name"))


def require_service(authorization: Annotated[str | None, Header()] = None) -> None:
    claims = _decode(_bearer(authorization), INTERNAL_AUDIENCE)
    if claims.get("sub") != "foxhood-web":
        raise _unauthorized("Unknown service")