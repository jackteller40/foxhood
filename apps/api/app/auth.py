"""Request authentication. The Next.js server signs a short-lived token for the signed-in user;
every protected endpoint verifies it here. User identity never comes from the browser."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Header, HTTPException, status

from app.settings import settings

AUDIENCE = "foxhood-api"
ISSUER = "foxhood-web"


@dataclass(frozen=True)
class CurrentUser:
    email: str
    name: str | None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized("Missing bearer token")
    try:
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            settings.api_jwt_secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "email"]},
        )
    except jwt.PyJWTError:
        raise _unauthorized("Invalid or expired token") from None

    email = str(claims["email"]).lower()
    if email not in settings.allowed_emails:  # checked here too, not only at sign-in
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not on the invite list")
    return CurrentUser(email=email, name=claims.get("name"))