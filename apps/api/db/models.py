"""Database tables. Sensitive fields are stored only as ciphertext in *_enc columns; db/repo.py
encrypts/decrypts them with AAD bound to table, column, owner and row (see db/crypto.py).

Plaintext on purpose: user email (needed to sign in), ids, kinds/sessions/statuses, timestamps,
and token usage. Everything about what someone owns, watches, said or was told is encrypted."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    profile_enc: Mapped[str | None] = mapped_column(Text)        # name, risk, horizon, interests
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)   # email_briefs, caps: not sensitive
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TS)


class Invite(Base):
    __tablename__ = "invites"
    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    invited_by: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    payload_enc: Mapped[str] = mapped_column(Text)   # {ticker, purchase_date, shares | amount}
    source: Mapped[str] = mapped_column(String(16), default="manual")   # manual | csv | agent | seed
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    payload_enc: Mapped[str] = mapped_column(Text)   # {ticker, note}
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_created", "user_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))     # preference | fact | brief_takeaway
    payload_enc: Mapped[str] = mapped_column(Text)    # {content, tags}
    source_run_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Brief(Base):
    __tablename__ = "briefs"
    __table_args__ = (UniqueConstraint("user_id", "brief_date", "session", name="uq_briefs_user_day_session"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    brief_date: Mapped[date] = mapped_column(Date)
    session: Mapped[str] = mapped_column(String(16))   # premarket | close
    content_enc: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class TraceEvent(Base):
    __tablename__ = "trace_events"
    __table_args__ = (Index("ix_trace_user_started", "user_id", "started_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(String(64))
    root_run_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="ok")
    input_enc: Mapped[str | None] = mapped_column(Text)    # tool args / prompts contain portfolio data
    output_enc: Mapped[str | None] = mapped_column(Text)
    error_enc: Mapped[str | None] = mapped_column(Text)    # errors can name tickers too
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    duration_ms: Mapped[float | None] = mapped_column(Float)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (Index("ix_usage_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)