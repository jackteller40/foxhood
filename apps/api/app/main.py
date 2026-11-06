"""Foxhood API."""
from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI

from app.auth import CurrentUser, get_current_user
from app.settings import settings

app = FastAPI(title="Foxhood API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        db = "ok"
    except Exception as e:
        db = f"error: {type(e).__name__}"
    return {"status": "ok", "db": db}


@app.get("/me")
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> dict:
    return {"email": user.email, "name": user.name}