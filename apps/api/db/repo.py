"""Data access. Every read/write of user data goes through UserRepo, which is bound to ONE verified
user id when it's created: every query filters on that id, and no method accepts another user's id.
Rows are encrypted and decrypted here; nothing above this layer ever sees ciphertext.

AdminRepo is operator-only (CLI, later the admin page) and is never built from request input."""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crypto import field_aad, get_cipher
from db.models import Holding, Invite, Memory, User, WatchlistItem, utcnow

RISK_LEVELS = {"low", "medium", "high"}
MEMORY_KINDS = {"preference", "fact", "brief_takeaway"}
HOLDING_SOURCES = {"manual", "csv", "agent", "seed"}
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
DEFAULT_PROFILE: dict[str, Any] = {"name": None, "persona": None, "risk_tolerance": "medium",
                                   "horizon": None, "interests": []}


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

    # ---- account ----
    async def export(self) -> dict:
        """Everything stored about this user, decrypted. (Briefs and traces join this in M2.)"""
        return _plain({
            "exported_at": utcnow(),
            "profile": await self.get_profile(),
            "holdings": [asdict(h) for h in await self.list_holdings()],
            "watchlist": [asdict(w) for w in await self.list_watchlist()],
            "memories": [asdict(m) for m in await self.list_memories(limit=10_000)],
        })

    async def delete_account(self) -> None:
        """Deletes the user; ON DELETE CASCADE removes every row they own, traces and usage included."""
        await self.s.execute(delete(User).where(User.id == self.user_id))
        await self.s.commit()


class AdminRepo:
    def __init__(self, session: AsyncSession):
        self.s = session

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