"""Foxhood API."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text

from app.routes import agent, internal, jobs, portfolio, user_data
from datasources.clients import DataProviderError
from db.crypto import DecryptionError
from db.repo import NotFound
from db.session import engine

log = logging.getLogger("foxhood.api")

app = FastAPI(title="Foxhood API", version="0.2.0")
app.include_router(user_data.router)
app.include_router(internal.router)
app.include_router(jobs.router)
app.include_router(agent.router)
app.include_router(portfolio.router)


@app.exception_handler(NotFound)
async def _not_found(_: Request, __: NotFound) -> JSONResponse:
    return JSONResponse({"detail": "Not found"}, status_code=404)


@app.exception_handler(DecryptionError)
async def _integrity_failure(_: Request, exc: DecryptionError) -> JSONResponse:
    log.error("Decryption failed: %s", exc)
    return JSONResponse({"detail": "Stored data failed an integrity check."}, status_code=500)


@app.exception_handler(DataProviderError)
async def _provider_down(_: Request, exc: DataProviderError) -> JSONResponse:
    log.warning("Market data provider error: %s", exc)
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(ValueError)
async def _invalid_input(_: Request, exc: ValueError) -> JSONResponse:
    if isinstance(exc, ValidationError):  # a response failed validation: our bug, not the caller's
        log.error("Response validation failed", exc_info=exc)
        return JSONResponse({"detail": "Internal error"}, status_code=500)
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.get("/health")
async def health() -> dict:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception as e:
        db = f"error: {type(e).__name__}"
    return {"status": "ok", "db": db}