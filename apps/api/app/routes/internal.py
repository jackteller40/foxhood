"""Server-to-server endpoints for the Next.js app. Hidden from the public docs; service token only."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import check_sign_in, require_service
from app.schemas import SignInCheckIn, SignInCheckOut
from db.repo import normalize_email
from db.session import get_session

router = APIRouter(prefix="/internal", include_in_schema=False, dependencies=[Depends(require_service)])


@router.post("/auth/check", response_model=SignInCheckOut)
async def check_sign_in_allowed(body: SignInCheckIn,
                                session: Annotated[AsyncSession, Depends(get_session)]) -> SignInCheckOut:
    try:
        email = normalize_email(body.email)
    except ValueError:
        return SignInCheckOut(allowed=False, reason="invalid_email")
    allowed, reason = await check_sign_in(session, email, body.google_sub)
    return SignInCheckOut(allowed=allowed, reason=reason)