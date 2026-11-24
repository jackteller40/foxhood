"""Endpoints Cloud Scheduler calls to run scheduled work (see jobs/). Not for browsers: they need the
X-Job-Key header to match JOBS_SECRET, and are switched off entirely when JOBS_SECRET isn't set."""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.settings import settings
from jobs.alerts import run_alerts
from jobs.morning_briefs import run_morning_briefs
from jobs.record import recorded


def require_job_key(x_job_key: Annotated[str | None, Header()] = None) -> None:
    if not settings.jobs_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Scheduled jobs are turned off (JOBS_SECRET not set).")
    if not x_job_key or not hmac.compare_digest(x_job_key, settings.jobs_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad job key")


router = APIRouter(prefix="/jobs", include_in_schema=False, dependencies=[Depends(require_job_key)])


def job_options() -> dict:
    """Extra arguments for the brief runs. Tests override this to use a scripted model and no MCP."""
    return {}


@router.post("/briefs")
async def morning_briefs(options: Annotated[dict, Depends(job_options)]) -> dict:
    return await recorded("briefs", lambda: run_morning_briefs(**options))


@router.post("/alerts")
async def alerts() -> dict:
    return await recorded("alerts", run_alerts)
