"""Admin page endpoints (only users with is_admin). Everything here is metadata: who's invited, when they
last signed in, how much AI they used, how runs and scheduled jobs went. Nothing decrypts anyone's
holdings, notes, conversations or briefs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUserDep, SessionDep
from app.schemas import AdminInviteIn
from app.settings import settings
from db.repo import AdminRepo, normalize_email


async def require_admin(user: CurrentUserDep, session: SessionDep) -> None:
    if not await AdminRepo(session).is_admin(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")


router = APIRouter(prefix="/admin", include_in_schema=False, dependencies=[Depends(require_admin)])
@router.get("/overview")
async def overview(session: SessionDep) -> dict:
    admin = AdminRepo(session)
    return {"spent_today_usd": float(await admin.global_spent_today()),
            "cap_total_usd": float(settings.daily_cap_total_usd), "cap_user_usd": float(settings.daily_cap_user_usd),
            "people": await admin.people()}


@router.get("/runs")
async def runs(session: SessionDep, limit: int = 40) -> list[dict]:
    return await AdminRepo(session).recent_runs(limit=max(1, min(limit, 200)))


@router.get("/jobs")
async def jobs(session: SessionDep) -> list[dict]:
    return [{"job": j.job, "started_at": j.started_at, "finished_at": j.finished_at, "ok": j.ok,
             "summary": j.summary} for j in await AdminRepo(session).job_runs()]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def invite(body: AdminInviteIn, user: CurrentUserDep, session: SessionDep) -> dict:
    inv = await AdminRepo(session).invite(body.email, invited_by=user.email)
    return {"email": inv.email}


@router.post("/invites/revoke")
async def revoke(body: AdminInviteIn, user: CurrentUserDep, session: SessionDep) -> dict:
    if normalize_email(body.email) == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't revoke your own invite.")
    if not await AdminRepo(session).revoke(body.email):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No invite for that email.")
    return {"email": normalize_email(body.email)}
