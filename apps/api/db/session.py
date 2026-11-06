"""Async database engine and sessions."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.settings import settings

# Tests run each test on a fresh event loop; pooled connections can't cross loops, so tests use NullPool.
_pool = {"poolclass": NullPool} if os.getenv("DB_NULLPOOL") == "1" else {"pool_pre_ping": True}
engine = create_async_engine(settings.database_url, **_pool)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with SessionLocal() as session:
        yield session