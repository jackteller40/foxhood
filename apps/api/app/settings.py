"""API settings from the environment. Fails fast if a required secret is missing."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

import core.config  # noqa: F401  (loads apps/api/.env)


@dataclass(frozen=True)
class ApiSettings:
    database_url: str
    api_jwt_secret: str
    daily_cap_user_usd: Decimal    # per person, resets at midnight ET
    daily_cap_total_usd: Decimal   # everyone combined: the kill switch for the Claude bill
    jobs_secret: str               # Cloud Scheduler sends it to /jobs/*; empty disables those endpoints
    resend_api_key: str            # empty: no email is sent (briefs and alerts still appear in the app)
    email_from: str
    app_url: str                   # links in emails point here


def _async_url(url: str) -> str:
    """SQLAlchemy async needs the driver in the URL; hosted Postgres usually gives plain postgresql://."""
    if url.startswith(("postgres://", "postgresql://")):
        return "postgresql+psycopg://" + url.split("://", 1)[1]
    return url


def _load() -> ApiSettings:
    secret = os.getenv("API_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("API_JWT_SECRET must be set and at least 32 characters (openssl rand -hex 32).")
    return ApiSettings(
        database_url=_async_url(os.getenv("DATABASE_URL", "postgresql+psycopg://foxhood:foxhood@localhost:5432/foxhood")),
        api_jwt_secret=secret,
        daily_cap_user_usd=Decimal(os.getenv("DAILY_CAP_USER_USD", "0.15")),
        daily_cap_total_usd=Decimal(os.getenv("DAILY_CAP_TOTAL_USD", "0.50")),
        jobs_secret=os.getenv("JOBS_SECRET", ""),
        resend_api_key=os.getenv("RESEND_API_KEY", ""),
        email_from=os.getenv("EMAIL_FROM", "Foxhood <brief@foxhood.app>"),
        app_url=os.getenv("APP_URL", "http://localhost:3000").rstrip("/"),
    )


settings = _load()