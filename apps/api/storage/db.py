"""SQLite storage: users, holdings, watchlist, memories, briefs, trace events."""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from core.config import settings

RISK_LEVELS = {"low", "medium", "high"}
MEMORY_KINDS = {"preference", "fact", "brief_takeaway"}
BRIEF_SESSIONS = {"premarket", "close"}
EVENT_TYPES = {"run", "llm", "tool", "mcp", "subagent", "skill", "memory", "permission", "error"}
MAX_PAYLOAD_CHARS = 20_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    persona         TEXT,
    risk_tolerance  TEXT NOT NULL,
    horizon         TEXT,
    interests       TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    purchase_date   TEXT NOT NULL,
    shares          REAL,
    amount          REAL,
    created_at      TEXT NOT NULL,
    CHECK ((shares IS NULL) <> (amount IS NULL))
);

CREATE TABLE IF NOT EXISTS watchlist (
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    note            TEXT,
    added_at        TEXT NOT NULL,
    PRIMARY KEY (user_id, ticker)
);

CREATE TABLE IF NOT EXISTS memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    content         TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    source_run_id   TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefs (
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brief_date      TEXT NOT NULL,
    session         TEXT NOT NULL,
    content_md      TEXT NOT NULL,
    run_id          TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (user_id, brief_date, session)
);

CREATE TABLE IF NOT EXISTS trace_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    parent_run_id   TEXT,
    root_run_id     TEXT NOT NULL,
    user_id         INTEGER,
    event_type      TEXT NOT NULL,
    name            TEXT NOT NULL,
    input_json      TEXT,
    output_json     TEXT,
    status          TEXT NOT NULL DEFAULT 'ok',
    error           TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_ms     REAL
);

CREATE INDEX IF NOT EXISTS idx_trace_root    ON trace_events(root_run_id, started_at);
CREATE INDEX IF NOT EXISTS idx_trace_user    ON trace_events(user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, created_at);
"""


# ---------- helpers ----------

def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    text = json.dumps(value, default=str)
    if len(text) > MAX_PAYLOAD_CHARS:
        text = json.dumps({"truncated": True, "preview": text[:MAX_PAYLOAD_CHARS]})
    return text


def _loads(text: str | None) -> Any:
    return json.loads(text) if text else None


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")  # lets Streamlit read while the agent writes traces
        conn.executescript(SCHEMA)


# ---------- users ----------

def _user(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["interests"] = _loads(d["interests"]) or []
    return d


def create_user(name: str, risk_tolerance: str, horizon: str | None = None,
                interests: list[str] | None = None, persona: str | None = None) -> int:
    if risk_tolerance not in RISK_LEVELS:
        raise ValueError(f"risk_tolerance must be one of {sorted(RISK_LEVELS)}")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (name, persona, risk_tolerance, horizon, interests, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, persona, risk_tolerance, horizon, json.dumps(interests or []), _now()),
        )
        return cur.lastrowid


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user(row) if row else None


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [_user(r) for r in rows]


def update_user(user_id: int, **fields: Any) -> None:
    allowed = {"name", "persona", "risk_tolerance", "horizon", "interests"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Can't update fields: {sorted(bad)}")
    if "risk_tolerance" in fields and fields["risk_tolerance"] not in RISK_LEVELS:
        raise ValueError(f"risk_tolerance must be one of {sorted(RISK_LEVELS)}")
    if "interests" in fields:
        fields["interests"] = json.dumps(fields["interests"] or [])
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), user_id))


# ---------- holdings (stored as entered; resolved to prices at read time) ----------

def add_holding(user_id: int, ticker: str, purchase_date: date,
                shares: float | None = None, amount: float | None = None) -> int:
    if (shares is None) == (amount is None):
        raise ValueError("Give exactly one of shares or amount.")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO holdings (user_id, ticker, purchase_date, shares, amount, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, ticker.strip().upper(), purchase_date.isoformat(), shares, amount, _now()),
        )
        return cur.lastrowid


def list_holdings(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM holdings WHERE user_id = ? ORDER BY purchase_date", (user_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["purchase_date"] = date.fromisoformat(d["purchase_date"])
        out.append(d)
    return out


def delete_holding(user_id: int, holding_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding_id, user_id))
        return cur.rowcount > 0


def holdings_as_lots(user_id: int) -> list:
    from portfolio.positions import Lot  # local import keeps storage independent of portfolio at import time
    return [
        Lot(h["ticker"], h["purchase_date"], shares=h["shares"], amount=h["amount"])
        for h in list_holdings(user_id)
    ]


# ---------- watchlist ----------

def add_to_watchlist(user_id: int, ticker: str, note: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO watchlist (user_id, ticker, note, added_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, ticker) DO UPDATE SET note = COALESCE(excluded.note, watchlist.note)",
            (user_id, ticker.strip().upper(), note, _now()),
        )


def remove_from_watchlist(user_id: int, ticker: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker.strip().upper())
        )
        return cur.rowcount > 0


def list_watchlist(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE user_id = ? ORDER BY ticker", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- memories (keyword + tag + recency retrieval) ----------

_STOPWORDS = {
    "the", "and", "for", "are", "any", "you", "your", "with", "that", "this", "what", "how",
    "should", "can", "about", "too", "was", "but", "not", "have", "has", "from", "into", "good",
}


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 3 or w in _STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("s"):  # naive plural strip: stocks -> stock
            w = w[:-1]
        out.add(w)
    return out


def _memory(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = _loads(d["tags"]) or []
    return d


def add_memory(user_id: int, kind: str, content: str, tags: list[str] | None = None,
               source_run_id: str | None = None) -> int:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"kind must be one of {sorted(MEMORY_KINDS)}")
    if not content.strip():
        raise ValueError("Memory content can't be empty.")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO memories (user_id, kind, content, tags, source_run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, kind, content.strip(), json.dumps(tags or []), source_run_id, _now()),
        )
        return cur.lastrowid


def list_memories(user_id: int, limit: int = 20, kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM memories WHERE user_id = ?"
    params: list[Any] = [user_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_memory(r) for r in rows]


def search_memories(user_id: int, query: str, limit: int = 5, kind: str | None = None) -> list[dict]:
    """Score = 2 x tag-word matches + content-word matches; ties go to the newest.
    An empty query returns the most recent memories."""
    candidates = list_memories(user_id, limit=500, kind=kind)  # newest first
    q = _tokens(query)
    if not q:
        return candidates[:limit]
    scored = []
    for rank, m in enumerate(candidates):
        searchable = _tokens(m["content"]) | _tokens(m["kind"].replace("_", " "))
        score = 2 * len(q & _tokens(" ".join(m["tags"]))) + len(q & searchable)
        if score:
            scored.append((score, -rank, m))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [dict(m, score=s) for s, _, m in scored[:limit]]


def delete_memory(user_id: int, memory_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, user_id))
        return cur.rowcount > 0


# ---------- briefs ----------

def save_brief(user_id: int, brief_date: date, session: str, content_md: str,
               run_id: str | None = None) -> None:
    if session not in BRIEF_SESSIONS:
        raise ValueError(f"session must be one of {sorted(BRIEF_SESSIONS)}")
    with connect() as conn:
        conn.execute(
            "INSERT INTO briefs (user_id, brief_date, session, content_md, run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, brief_date, session) DO UPDATE SET "
            "content_md = excluded.content_md, run_id = excluded.run_id, created_at = excluded.created_at",
            (user_id, brief_date.isoformat(), session, content_md, run_id, _now()),
        )


def get_brief(user_id: int, brief_date: date, session: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM briefs WHERE user_id = ? AND brief_date = ? AND session = ?",
            (user_id, brief_date.isoformat(), session),
        ).fetchone()
    return dict(row) if row else None


def latest_brief(user_id: int, session: str | None = None) -> dict | None:
    sql = "SELECT * FROM briefs WHERE user_id = ?"
    params: list[Any] = [user_id]
    if session:
        sql += " AND session = ?"
        params.append(session)
    sql += " ORDER BY brief_date DESC, created_at DESC LIMIT 1"
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


# ---------- trace events ----------

def log_trace_event(*, run_id: str, root_run_id: str, event_type: str, name: str,
                    parent_run_id: str | None = None, user_id: int | None = None,
                    input: Any = None, output: Any = None, status: str = "ok",
                    error: str | None = None, started_at: str | None = None,
                    ended_at: str | None = None, duration_ms: float | None = None) -> int:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of {sorted(EVENT_TYPES)}")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO trace_events (run_id, parent_run_id, root_run_id, user_id, event_type, name, "
            "input_json, output_json, status, error, started_at, ended_at, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, parent_run_id, root_run_id, user_id, event_type, name,
             _dumps(input), _dumps(output), status, error,
             started_at or _now(), ended_at, duration_ms),
        )
        return cur.lastrowid


def get_run_events(root_run_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trace_events WHERE root_run_id = ? ORDER BY started_at, id", (root_run_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["input"] = _loads(d.pop("input_json"))
        d["output"] = _loads(d.pop("output_json"))
        out.append(d)
    return out


def list_runs(user_id: int | None = None, limit: int = 20) -> list[dict]:
    """One row per agent run, newest first, for the Trace page's run picker."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT root_run_id,
                   MAX(CASE WHEN event_type = 'run' THEN name END)          AS run_name,
                   MAX(CASE WHEN event_type = 'run' THEN status END)        AS run_status,
                   MAX(CASE WHEN event_type = 'run' THEN parent_run_id END) AS resumes_run_id,
                   MIN(started_at)                          AS run_started,
                   MAX(COALESCE(ended_at, started_at))      AS run_ended,
                   COUNT(*)                                 AS events,
                   SUM(status = 'error')                    AS errors,
                   SUM(status = 'denied')                   AS denials
            FROM trace_events
            WHERE (? IS NULL OR user_id = ?)
            GROUP BY root_run_id
            ORDER BY run_started DESC
            LIMIT ?
            """,
            (user_id, user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]