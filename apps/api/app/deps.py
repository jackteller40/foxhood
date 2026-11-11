"""Shared FastAPI dependencies. Handlers that touch user data take RepoDep: a UserRepo already bound
to the verified caller. The request's DB session is shared by auth and the repo (FastAPI reuses it)."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from db.repo import UserRepo
from db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def get_repo(user: CurrentUserDep, session: SessionDep) -> UserRepo:
    return UserRepo(session, user.id)


RepoDep = Annotated[UserRepo, Depends(get_repo)]