"""Data access. Every read/write of user data goes through UserRepo, which is bound to ONE verified
user id when it's created: every query filters on that id, and no method accepts another user's id.
Rows are encrypted and decrypted here; nothing above this layer ever sees ciphertext.

AdminRepo is operator-only (CLI, later the admin page) and is never built from request input."""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.crypto import field_aad, get_cipher
from db.models import Brief, ChatThread, Holding, Invite, Memory, TraceEvent, Usage, User, WatchlistItem, utcnow

RISK_LEVELS = {"low", "medium", "high"}
MEMORY_KINDS = {"preference", "fact", "brief_takeaway"}
HOLDING_SOURCES = {"manual", "csv", "agent", "seed"}
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
DEFAULT_PROFILE: dict[str, Any] = {"name": None, "persona": None, "risk_tolerance": "medium",
                                   "horizon": None, "interests": []}

BRIEF_SESSIONS = {"premarket", "close"}
EVENT_TYPES = {"run", "llm", "tool", "mcp", "subagent", "skill", "memory", "permission", "error"}
ET = ZoneInfo("America/New_York")


def start_of_today_et() -> datetime:
    """Midnight US/Eastern today: daily spending caps reset here."""
    return datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)


class NotFound(Exception):
    """Row doesn't exist OR belongs to someone else; callers can't tell which (API returns 404)."""


def normalize_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker {ticker!r}")
    return t


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e or len(e) > 320:
        raise ValueError(f"Invalid email {email!r}")
    return e


def _plain(obj: Any) -> Any:
    """Make dataclass/dict output JSON-safe (UUIDs, dates)."""
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


@dataclass(frozen=True)
class HoldingRecord:
    id: uuid.UUID
    ticker: str
    purchase_date: date
    shares: float | None
    amount: float | None
    source: str
    created_at: datetime

    def to_lot(self):
        from portfolio.positions import Lot
        return Lot(self.ticker, self.purchase_date, shares=self.shares, amount=self.amount)


@dataclass(frozen=True)
class WatchRecord:
    id: uuid.UUID
    ticker: str
    note: str | None
    created_at: datetime


@dataclass(frozen=True)
class MemoryRecord:
    id: uuid.UUID
    kind: str
    content: str
    tags: list[str]
    source_run_id: str | None
    created_at: datetime
    
@dataclass(frozen=True)
class BriefRecord:
    id: uuid.UUID
    brief_date: date
    session: str
    content: str
    run_id: str | None
    created_at: datetime
    
@dataclass(frozen=True)
class ThreadRecord:
    id: str
    task: str
    title: str
    archived: bool
    created_at: datetime
    last_active_at: datetime


def thread_title(text: str | None, limit: int = 60) -> str:
    """A readable title from the first question: one line, cut at a word boundary."""
    t = " ".join((text or "").split())
    if not t:
        return "New chat"
    if len(t) <= limit:
        return t
    return (t[:limit].rsplit(" ", 1)[0] or t[:limit]) + "…"


# ---------- memory keyword search (same scoring as the POC) ----------
_STOPWORDS = {"the", "and", "for", "are", "any", "you", "your", "with", "that", "this", "what", "how",
              "should", "can", "about", "too", "was", "but", "not", "have", "has", "from", "into", "good"}


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 3 or w in _STOPWORDS:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


class UserRepo:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID):
        self.s = session
        self.user_id = user_id
        self._cipher = get_cipher()

    # ---- helpers ----
    def _enc(self, table: str, column: str, row_id: uuid.UUID, value: Any) -> str:
        return self._cipher.encrypt_json(value, field_aad(table, column, self.user_id, row_id))

    def _dec(self, table: str, column: str, row_id: uuid.UUID, token: str) -> Any:
        return self._cipher.decrypt_json(token, field_aad(table, column, self.user_id, row_id))

    async def _get_owned(self, model, row_id: uuid.UUID):
        q = select(model).where(model.id == row_id, model.user_id == self.user_id)
        row = (await self.s.execute(q)).scalar_one_or_none()
        if row is None:
            raise NotFound(model.__tablename__)
        return row

    # ---- profile ----
    async def get_profile(self) -> dict:
        user = await self.s.get(User, self.user_id)
        if user is None:
            raise NotFound("users")
        profile = dict(DEFAULT_PROFILE)
        if user.profile_enc:
            profile.update(self._dec("users", "profile", self.user_id, user.profile_enc))
        return {"email": user.email, **profile}

    async def update_profile(self, **fields: Any) -> dict:
        unknown = set(fields) - set(DEFAULT_PROFILE)
        if unknown:
            raise ValueError(f"Unknown profile fields: {sorted(unknown)}")
        if "risk_tolerance" in fields and fields["risk_tolerance"] not in RISK_LEVELS:
            raise ValueError(f"risk_tolerance must be one of {sorted(RISK_LEVELS)}")
        if "interests" in fields:
            interests = [str(i).strip()[:60] for i in (fields["interests"] or []) if str(i).strip()]
            if len(interests) > 20:
                raise ValueError("At most 20 interests")
            fields["interests"] = interests
        for key in ("name", "persona", "horizon"):
            if fields.get(key) is not None:
                fields[key] = str(fields[key]).strip()[:100] or None

        user = await self.s.get(User, self.user_id)
        if user is None:
            raise NotFound("users")
        current = {k: v for k, v in (await self.get_profile()).items() if k in DEFAULT_PROFILE}
        current.update(fields)
        user.profile_enc = self._enc("users", "profile", self.user_id, current)
        await self.s.commit()
        return await self.get_profile()

    # ---- holdings ----
    def _holding(self, row: Holding) -> HoldingRecord:
        p = self._dec("holdings", "payload", row.id, row.payload_enc)
        return HoldingRecord(row.id, p["ticker"], date.fromisoformat(p["purchase_date"]),
                             p.get("shares"), p.get("amount"), row.source, row.created_at)

    async def list_holdings(self) -> list[HoldingRecord]:
        rows = (await self.s.execute(select(Holding).where(Holding.user_id == self.user_id))).scalars().all()
        return sorted((self._holding(r) for r in rows), key=lambda h: (h.purchase_date, h.ticker))

    async def get_holding(self, holding_id: uuid.UUID) -> HoldingRecord:
        return self._holding(await self._get_owned(Holding, holding_id))

    async def add_holding(self, ticker: str, purchase_date: date, shares: float | None = None,
                          amount: float | None = None, source: str = "manual") -> HoldingRecord:
        if (shares is None) == (amount is None):
            raise ValueError("Give exactly one of shares or amount.")
        if (shares if shares is not None else amount) <= 0:
            raise ValueError("Shares or amount must be greater than zero.")
        if purchase_date > date.today():
            raise ValueError("Purchase date can't be in the future.")
        if source not in HOLDING_SOURCES:
            raise ValueError(f"source must be one of {sorted(HOLDING_SOURCES)}")
        hid = uuid.uuid4()
        payload = {"ticker": normalize_ticker(ticker), "purchase_date": purchase_date.isoformat(),
                   "shares": float(shares) if shares is not None else None,
                   "amount": float(amount) if amount is not None else None}
        row = Holding(id=hid, user_id=self.user_id, source=source,
                      payload_enc=self._enc("holdings", "payload", hid, payload))
        self.s.add(row)
        await self.s.commit()
        return self._holding(row)

    async def delete_holding(self, holding_id: uuid.UUID) -> None:
        await self.s.delete(await self._get_owned(Holding, holding_id))
        await self.s.commit()

    # ---- watchlist ----
    def _watch(self, row: WatchlistItem) -> WatchRecord:
        p = self._dec("watchlist", "payload", row.id, row.payload_enc)
        return WatchRecord(row.id, p["ticker"], p.get("note"), row.created_at)

    async def list_watchlist(self) -> list[WatchRecord]:
        q = select(WatchlistItem).where(WatchlistItem.user_id == self.user_id)
        return sorted((self._watch(r) for r in (await self.s.execute(q)).scalars().all()), key=lambda w: w.ticker)

    async def add_to_watchlist(self, ticker: str, note: str | None = None) -> tuple[WatchRecord, bool]:
        """Returns (item, created). An existing ticker is returned unchanged (its note is never overwritten)."""
        t = normalize_ticker(ticker)
        for w in await self.list_watchlist():
            if w.ticker == t:
                return w, False
        wid = uuid.uuid4()
        clean_note = (note or "").strip()[:200] or None
        row = WatchlistItem(id=wid, user_id=self.user_id,
                            payload_enc=self._enc("watchlist", "payload", wid, {"ticker": t, "note": clean_note}))
        self.s.add(row)
        await self.s.commit()
        return self._watch(row), True

    async def remove_from_watchlist(self, ticker: str) -> bool:
        t = normalize_ticker(ticker)
        for w in await self.list_watchlist():
            if w.ticker == t:
                await self.delete_watch_item(w.id)
                return True
        return False

    async def delete_watch_item(self, item_id: uuid.UUID) -> None:
        await self.s.delete(await self._get_owned(WatchlistItem, item_id))
        await self.s.commit()

    # ---- memories ----
    def _memory(self, row: Memory) -> MemoryRecord:
        p = self._dec("memories", "payload", row.id, row.payload_enc)
        return MemoryRecord(row.id, row.kind, p["content"], p.get("tags", []), row.source_run_id, row.created_at)

    async def list_memories(self, kind: str | None = None, limit: int = 100) -> list[MemoryRecord]:
        q = select(Memory).where(Memory.user_id == self.user_id)
        if kind:
            q = q.where(Memory.kind == kind)
        q = q.order_by(Memory.created_at.desc()).limit(limit)
        return [self._memory(r) for r in (await self.s.execute(q)).scalars().all()]

    async def add_memory(self, kind: str, content: str, tags: list[str] | None = None,
                         source_run_id: str | None = None) -> MemoryRecord:
        if kind not in MEMORY_KINDS:
            raise ValueError(f"kind must be one of {sorted(MEMORY_KINDS)}")
        content = (content or "").strip()
        if not content or len(content) > 1000:
            raise ValueError("Memory content must be 1-1000 characters.")
        clean_tags = [str(t).strip()[:40] for t in (tags or []) if str(t).strip()][:10]
        mid = uuid.uuid4()
        row = Memory(id=mid, user_id=self.user_id, kind=kind, source_run_id=source_run_id,
                     payload_enc=self._enc("memories", "payload", mid, {"content": content, "tags": clean_tags}))
        self.s.add(row)
        await self.s.commit()
        return self._memory(row)

    async def search_memories(self, query: str, limit: int = 5) -> list[tuple[int, MemoryRecord]]:
        """Score = 2 x tag-word matches + content/kind-word matches; ties go to the newest.
        Decrypted and scored in Python: ciphertext can't be searched in SQL, and per-user counts are small."""
        candidates = await self.list_memories(limit=500)
        q = _tokens(query)
        if not q:
            return [(0, m) for m in candidates[:limit]]
        scored = []
        for rank, m in enumerate(candidates):
            searchable = _tokens(m.content) | _tokens(m.kind.replace("_", " "))
            score = 2 * len(q & _tokens(" ".join(m.tags))) + len(q & searchable)
            if score:
                scored.append((score, -rank, m))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [(s, m) for s, _, m in scored[:limit]]

    async def delete_memory(self, memory_id: uuid.UUID) -> None:
        await self.s.delete(await self._get_owned(Memory, memory_id))
        await self.s.commit()

        # ---- briefs ----
    def _brief(self, row: Brief) -> BriefRecord:
        return BriefRecord(row.id, row.brief_date, row.session,
                           self._dec("briefs", "content", row.id, row.content_enc), row.run_id, row.created_at)

    async def get_brief(self, brief_date: date, session: str) -> BriefRecord | None:
        q = select(Brief).where(Brief.user_id == self.user_id, Brief.brief_date == brief_date,
                                Brief.session == session)
        row = (await self.s.execute(q)).scalar_one_or_none()
        return self._brief(row) if row else None

    async def list_briefs(self, limit: int = 30) -> list[BriefRecord]:
        q = (select(Brief).where(Brief.user_id == self.user_id)
             .order_by(Brief.brief_date.desc(), Brief.created_at.desc()).limit(limit))
        return [self._brief(r) for r in (await self.s.execute(q)).scalars().all()]

    async def save_brief(self, brief_date: date, session: str, content: str, run_id: str | None = None) -> BriefRecord:
        """One brief per user per trading day per session; saving again replaces it."""
        if session not in BRIEF_SESSIONS:
            raise ValueError(f"session must be one of {sorted(BRIEF_SESSIONS)}")
        q = select(Brief).where(Brief.user_id == self.user_id, Brief.brief_date == brief_date,
                                Brief.session == session)
        row = (await self.s.execute(q)).scalar_one_or_none()
        if row is None:
            bid = uuid.uuid4()
            row = Brief(id=bid, user_id=self.user_id, brief_date=brief_date, session=session, run_id=run_id,
                        content_enc=self._enc("briefs", "content", bid, content))
            self.s.add(row)
        else:
            row.content_enc = self._enc("briefs", "content", row.id, content)
            row.run_id = run_id
            row.created_at = utcnow()
        await self.s.commit()
        return self._brief(row)

        # ---- chat threads (ownership + titles; the messages themselves are in the checkpoints) ----
    def _thread(self, row: ChatThread) -> ThreadRecord:
        return ThreadRecord(row.id, row.task, self._dec("chat_threads", "title", row.id, row.title_enc),
                            row.archived, row.created_at, row.last_active_at)

    async def touch_thread(self, thread_id: str, task: str, title: str | None = None) -> ThreadRecord:
        """Called at the start of every agent run: creates the thread on its first turn, else bumps it.
        Someone else's thread id raises NotFound, exactly like a thread that doesn't exist."""
        row = await self.s.get(ChatThread, thread_id)
        if row is not None and row.user_id != self.user_id:
            raise NotFound("chat_threads")
        if row is None:
            row = ChatThread(id=thread_id, user_id=self.user_id, task=task[:32],
                             title_enc=self._enc("chat_threads", "title", thread_id, thread_title(title)))
            self.s.add(row)
        else:
            row.last_active_at = utcnow()
        await self.s.commit()
        return self._thread(row)

    async def get_thread(self, thread_id: str) -> ThreadRecord:
        return self._thread(await self._get_owned(ChatThread, thread_id))

    async def list_threads(self, task: str | None = "chat", include_archived: bool = False,
                           limit: int = 50) -> list[ThreadRecord]:
        q = select(ChatThread).where(ChatThread.user_id == self.user_id)
        if task is not None:
            q = q.where(ChatThread.task == task)
        if not include_archived:
            q = q.where(ChatThread.archived.is_(False))
        q = q.order_by(ChatThread.last_active_at.desc()).limit(limit)
        return [self._thread(r) for r in (await self.s.execute(q)).scalars().all()]

    async def rename_thread(self, thread_id: str, title: str) -> ThreadRecord:
        row = await self._get_owned(ChatThread, thread_id)
        row.title_enc = self._enc("chat_threads", "title", thread_id, thread_title(title, limit=100))
        await self.s.commit()
        return self._thread(row)

    async def archive_thread(self, thread_id: str, archived: bool = True) -> ThreadRecord:
        row = await self._get_owned(ChatThread, thread_id)
        row.archived = archived
        await self.s.commit()
        return self._thread(row)

    async def delete_thread(self, thread_id: str) -> None:
        """Removes the thread row only. Use agent.runner.delete_thread to also erase its messages."""
        await self.s.delete(await self._get_owned(ChatThread, thread_id))
        await self.s.commit()
        
    # ---- traces (inputs, outputs and errors encrypted; bound to each event's unique run_id) ----
    def _trace_enc(self, column: str, run_id: str, value: Any) -> str | None:
        return None if value is None else self._enc("trace_events", column, run_id, value)

    def _trace_dec(self, column: str, run_id: str, token: str | None) -> Any:
        return None if token is None else self._dec("trace_events", column, run_id, token)

    async def add_trace_events(self, events: list[dict]) -> None:
        """Bulk-save one run's events (the runner calls this once, when the run ends)."""
        rows = []
        for e in events:
            if e["event_type"] not in EVENT_TYPES:
                raise ValueError(f"Unknown event_type {e['event_type']!r}")
            rid = str(e["run_id"])
            rows.append(TraceEvent(
                run_id=rid, parent_run_id=e.get("parent_run_id"), root_run_id=str(e["root_run_id"]),
                user_id=self.user_id, event_type=e["event_type"], name=str(e["name"])[:128],
                status=e.get("status", "ok"),
                input_enc=self._trace_enc("input", rid, e.get("input")),
                output_enc=self._trace_enc("output", rid, e.get("output")),
                error_enc=self._trace_enc("error", rid, e.get("error")),
                started_at=e["started_at"], ended_at=e.get("ended_at"), duration_ms=e.get("duration_ms"),
            ))
        self.s.add_all(rows)
        await self.s.commit()

    async def get_run_events(self, root_run_id: str) -> list[dict]:
        q = (select(TraceEvent)
             .where(TraceEvent.user_id == self.user_id, TraceEvent.root_run_id == root_run_id)
             .order_by(TraceEvent.started_at, TraceEvent.id))
        rows = (await self.s.execute(q)).scalars().all()
        if not rows:
            raise NotFound("trace_events")
        return [{
            "run_id": r.run_id, "parent_run_id": r.parent_run_id, "root_run_id": r.root_run_id,
            "event_type": r.event_type, "name": r.name, "status": r.status,
            "input": self._trace_dec("input", r.run_id, r.input_enc),
            "output": self._trace_dec("output", r.run_id, r.output_enc),
            "error": self._trace_dec("error", r.run_id, r.error_enc),
            "started_at": r.started_at, "ended_at": r.ended_at, "duration_ms": r.duration_ms,
        } for r in rows]

    async def list_runs(self, limit: int = 20) -> list[dict]:
        """One summary row per agent run, newest first (no encrypted content needed)."""
        t = TraceEvent
        q = (select(
                t.root_run_id,
                func.max(case((t.event_type == "run", t.name))).label("run_name"),
                func.max(case((t.event_type == "run", t.status))).label("run_status"),
                func.max(case((t.event_type == "run", t.parent_run_id))).label("resumes_run_id"),
                func.min(t.started_at).label("started_at"),
                func.max(func.coalesce(t.ended_at, t.started_at)).label("ended_at"),
                func.count().label("events"),
                func.count().filter(t.status == "error").label("errors"),
                func.count().filter(t.status == "denied").label("denials"))
             .where(t.user_id == self.user_id)
             .group_by(t.root_run_id)
             .order_by(func.min(t.started_at).desc())
             .limit(limit))
        return [dict(r._mapping) for r in (await self.s.execute(q)).all()]

    # ---- usage (plaintext: token counts and cost reveal nothing about holdings) ----
    async def add_usage(self, run_id: str, model: str, input_tokens: int, output_tokens: int,
                        cost_usd: Decimal | float = Decimal(0)) -> None:
        self.s.add(Usage(user_id=self.user_id, run_id=run_id, model=model[:64], input_tokens=int(input_tokens),
                         output_tokens=int(output_tokens), cost_usd=Decimal(str(cost_usd))))
        await self.s.commit()

    async def spent_today(self) -> Decimal:
        q = (select(func.coalesce(func.sum(Usage.cost_usd), 0))
             .where(Usage.user_id == self.user_id, Usage.created_at >= start_of_today_et()))
        return Decimal((await self.s.execute(q)).scalar_one())
    
    # ---- account ----
    async def export(self) -> dict:
        """Everything stored about this user, decrypted. (Briefs and traces join this in M2.)"""
        return _plain({
            "exported_at": utcnow(),
            "profile": await self.get_profile(),
            "holdings": [asdict(h) for h in await self.list_holdings()],
            "watchlist": [asdict(w) for w in await self.list_watchlist()],
            "memories": [asdict(m) for m in await self.list_memories(limit=10_000)],
            "briefs": [asdict(b) for b in await self.list_briefs(limit=10_000)],
            "chat_threads": [asdict(t) for t in await self.list_threads(task=None, include_archived=True,
                                                                         limit=10_000)],
        })

    async def delete_account(self) -> None:
        """Deletes the user; ON DELETE CASCADE removes every row they own, traces and usage included."""
        await self.s.execute(delete(User).where(User.id == self.user_id))
        await self.s.commit()


class AdminRepo:
    def __init__(self, session: AsyncSession):
        self.s = session
        
    async def global_spent_today(self) -> Decimal:
        q = select(func.coalesce(func.sum(Usage.cost_usd), 0)).where(Usage.created_at >= start_of_today_et())
        return Decimal((await self.s.execute(q)).scalar_one())

    async def invite(self, email: str, invited_by: str | None = None) -> Invite:
        e = normalize_email(email)
        inv = await self.s.get(Invite, e)
        if inv is None:
            inv = Invite(email=e, invited_by=invited_by)
            self.s.add(inv)
        else:
            inv.revoked_at = None  # re-inviting restores access
        await self.s.commit()
        return inv

    async def revoke(self, email: str) -> bool:
        inv = await self.s.get(Invite, normalize_email(email))
        if inv is None:
            return False
        inv.revoked_at = utcnow()
        await self.s.commit()
        return True

    async def is_invited(self, email: str) -> bool:
        inv = await self.s.get(Invite, normalize_email(email))
        return bool(inv and inv.revoked_at is None)

    async def list_invites(self) -> list[Invite]:
        return list((await self.s.execute(select(Invite).order_by(Invite.created_at))).scalars().all())

    async def get_or_create_user(self, email: str, google_sub: str | None = None) -> User:
        e = normalize_email(email)
        user = (await self.s.execute(select(User).where(User.email == e))).scalar_one_or_none()
        if user is None:
            user = User(email=e, google_sub=google_sub)
            self.s.add(user)
        elif google_sub and not user.google_sub:
            user.google_sub = google_sub
        await self.s.commit()
        return user

    async def list_users(self) -> list[dict]:
        users = (await self.s.execute(select(User).order_by(User.created_at))).scalars().all()
        out = []
        for u in users:
            counts = {}
            for label, model in (("holdings", Holding), ("watchlist", WatchlistItem), ("memories", Memory)):
                q = select(func.count()).select_from(model).where(model.user_id == u.id)
                counts[label] = (await self.s.execute(q)).scalar_one()
            out.append({"email": u.email, "created_at": u.created_at, "last_login_at": u.last_login_at, **counts})
        return out
    
    async def find_user(self, email: str) -> User | None:
        q = select(User).where(User.email == normalize_email(email))
        return (await self.s.execute(q)).scalar_one_or_none()

    async def record_login(self, email: str, google_sub: str) -> User:
        """Runs on every authenticated request, after the invite check. Creates the user on first
        sign-in, links their Google account, marks the invite accepted, and refreshes last_login_at
        at most hourly (so normal browsing doesn't write to the database on every request)."""
        e = normalize_email(email)
        now = utcnow()
        user = await self.find_user(e)
        changed = False
        if user is None:
            user = User(email=e, google_sub=google_sub, last_login_at=now)
            self.s.add(user)
            changed = True
        else:
            if not user.google_sub:
                user.google_sub = google_sub
                changed = True
            if user.last_login_at is None or now - user.last_login_at > timedelta(hours=1):
                user.last_login_at = now
                changed = True
        inv = await self.s.get(Invite, e)
        if inv is not None and inv.accepted_at is None:
            inv.accepted_at = now
            changed = True
        if changed:
            try:
                await self.s.commit()
            except IntegrityError:  # two first requests raced to create the user; use the winner's row
                await self.s.rollback()
                user = await self.find_user(e)
        return user