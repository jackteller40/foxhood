"""Request and response shapes. Inputs reject unknown fields; outputs never include ciphertext."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProfileOut(_Out):
    email: str
    name: str | None = None
    persona: str | None = None
    risk_tolerance: str
    horizon: str | None = None
    interests: list[str] = []


class ProfileUpdate(_In):
    name: str | None = Field(None, max_length=100)
    persona: str | None = Field(None, max_length=100)
    risk_tolerance: Literal["low", "medium", "high"] | None = None
    horizon: str | None = Field(None, max_length=100)
    interests: list[str] | None = Field(None, max_length=20)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    profile: ProfileOut


class HoldingIn(_In):
    ticker: str = Field(min_length=1, max_length=12)
    purchase_date: date
    shares: float | None = Field(None, gt=0)
    amount: float | None = Field(None, gt=0, le=10_000_000)

    @model_validator(mode="after")
    def exactly_one_quantity(self) -> HoldingIn:
        if (self.shares is None) == (self.amount is None):
            raise ValueError("Give exactly one of shares or amount.")
        return self


class HoldingOut(_Out):
    id: uuid.UUID
    ticker: str
    purchase_date: date
    shares: float | None
    amount: float | None
    source: str
    created_at: datetime


class WatchIn(_In):
    ticker: str = Field(min_length=1, max_length=12)
    note: str | None = Field(None, max_length=200)


class WatchOut(_Out):
    id: uuid.UUID
    ticker: str
    note: str | None
    created_at: datetime


class SettingsOut(BaseModel):
    scheduled_briefs: bool
    email_briefs: bool
    email_alerts: bool
    max_position_pct: float | None


class SettingsUpdate(_In):
    scheduled_briefs: bool | None = None
    email_briefs: bool | None = None
    email_alerts: bool | None = None
    max_position_pct: float | None = Field(None, ge=1, le=100)   # send null to clear the limit


class AlertOut(BaseModel):
    id: uuid.UUID
    kind: str
    ticker: str
    message: str
    created_at: datetime


class MemoryIn(_In):
    kind: Literal["preference", "fact"] = "preference"  # brief_takeaway is written by the agent only
    content: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)


class MemoryOut(_Out):
    id: uuid.UUID
    kind: str
    content: str
    tags: list[str]
    source_run_id: str | None
    created_at: datetime


class DeleteAccountIn(_In):
    confirm: Literal["DELETE"]


class SignInCheckIn(_In):
    email: str = Field(max_length=320)
    google_sub: str = Field(min_length=1, max_length=255)


class SignInCheckOut(BaseModel):
    allowed: bool
    reason: str


class AdminInviteIn(_In):
    email: str = Field(min_length=3, max_length=320)

# ---- agent ----
class ChatIn(_In):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(None, max_length=128)


class Decision(_In):
    approved: bool
    note: str | None = Field(None, max_length=200)


class ApproveIn(_In):
    decisions: dict[str, Decision] = Field(min_length=1)   # tool_call_id -> decision
    run_id: str | None = Field(None, max_length=64)        # the paused run, for linking traces


class ThreadOut(_Out):
    id: str
    title: str
    archived: bool
    created_at: datetime
    last_active_at: datetime


class ThreadUpdate(_In):
    title: str | None = Field(None, min_length=1, max_length=100)
    archived: bool | None = None


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    tools: list[str] = []


class ThreadDetailOut(BaseModel):
    thread: ThreadOut
    messages: list[ChatMessageOut]
    pending: list[dict]


class BriefOut(_Out):
    brief_date: date
    session: str
    content: str
    created_at: datetime


class UsageOut(BaseModel):
    spent_usd: float
    cap_usd: float
    remaining_usd: float
    resets: str = "midnight US/Eastern"


# ---- portfolio import ----
class ImportPreviewIn(_In):
    csv: str = Field(min_length=1, max_length=200_000)
    default_date: date | None = None   # for files without a date column, e.g. a broker's positions export


class ImportRowOut(BaseModel):
    row: int
    ticker: str
    status: Literal["ok", "error"]
    purchase_date: date | None = None
    shares: float | None = None
    amount: float | None = None
    error: str | None = None
    trade_date: date | None = None
    price_paid: float | None = None
    shares_now: float | None = None
    cost_basis: float | None = None
    note: str | None = None
    broker_cost_basis: float | None = None   # what the broker's file says you paid, to compare with


class SkippedRowOut(BaseModel):
    row: int
    ticker: str
    reason: str


class ImportPreviewOut(BaseModel):
    rows: list[ImportRowOut]
    ok: int
    errors: int
    skipped: list[SkippedRowOut] = []


class ImportCommitIn(_In):
    rows: list[HoldingIn] = Field(min_length=1, max_length=200)


class ImportCommitOut(BaseModel):
    created: int
