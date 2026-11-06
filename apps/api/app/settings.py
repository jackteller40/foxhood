"""API settings from the environment. Fails fast if a required secret is missing."""
from __future__ import annotations

import os
from dataclasses import dataclass

import core.config  # noqa: F401  (loads apps/api/.env)


def _email_set(raw: str) -> frozenset[str]:
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


@dataclass(frozen=True)
class ApiSettings:
    database_url: str
    api_jwt_secret: str
    allowed_emails: frozenset[str]


def _load() -> ApiSettings:
    secret = os.getenv("API_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("API_JWT_SECRET must be set and at least 32 characters (openssl rand -hex 32).")
    return ApiSettings(
        database_url=os.getenv("DATABASE_URL", "postgresql://foxhood:foxhood@localhost:5432/foxhood"),
        api_jwt_secret=secret,
        allowed_emails=_email_set(os.getenv("ALLOWED_EMAILS", "")),
    )


settings = _load()