"""Foxhood API."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text

from app.auth import CurrentUser, get_current_user
from db.session import engine

app = FastAPI(title="Foxhood API", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception as e:
        db = f"error: {type(e).__name__}"
    return {"status": "ok", "db": db}


@app.get("/me")
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> dict:
    return {"email": user.email, "name": user.name}