"""Shared cache for PUBLIC market data, stored in Postgres (table market_cache).

Why Postgres: Cloud Run's disk is temporary and several instances may run at once; one shared table
means a fetch serves every instance and every user. Values are JSON, never pickle (loading a pickle
can execute code). Keys come only from function names and public arguments (tickers, dates), so no
user data is ever cached here. If the database is unreachable, functions just run uncached."""
from __future__ import annotations

import functools
import hashlib
import io
import json
import logging
import os
import random
import threading
from typing import Any, Callable

import pandas as pd
from psycopg_pool import ConnectionPool

import core.config  # noqa: F401  (loads apps/api/.env)

log = logging.getLogger(__name__)
MISS = object()  # sentinel: "not in cache" (None can be a real cached value)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _dsn() -> str:
    url = os.getenv("DATABASE_URL", "postgresql://foxhood:foxhood@localhost:5432/foxhood")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)  # plain psycopg wants no driver suffix


def _get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(_dsn(), min_size=0, max_size=4, timeout=5, open=True)
        return _pool


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return value.empty
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False


def _encode(value: Any) -> str:
    if isinstance(value, pd.DataFrame):
        return json.dumps({"__type__": "df", "data": value.to_json(orient="split", date_format="iso")})
    if isinstance(value, pd.Series):
        return json.dumps({"__type__": "series", "name": value.name,
                           "data": value.to_json(orient="split", date_format="iso")})
    return json.dumps({"__type__": "json", "data": value}, default=str)


def _decode(text: str) -> Any:
    obj = json.loads(text)
    if obj["__type__"] == "df":
        return pd.read_json(io.StringIO(obj["data"]), orient="split")
    if obj["__type__"] == "series":
        s = pd.read_json(io.StringIO(obj["data"]), orient="split", typ="series")
        s.name = obj["name"]
        return s
    return obj["data"]


def make_key(namespace: str, *parts: Any) -> str:
    return hashlib.sha256((namespace + "|" + "|".join(repr(p) for p in parts)).encode()).hexdigest()


def cache_get(key: str) -> Any:
    """The cached value, or MISS (absent, expired, unreadable, or database down)."""
    try:
        with _get_pool().connection() as conn:
            row = conn.execute("SELECT value FROM market_cache WHERE key = %s AND expires_at > now()",
                               (key,)).fetchone()
    except Exception:
        log.warning("Cache read failed; continuing uncached", exc_info=True)
        return MISS
    if row is None:
        return MISS
    try:
        return _decode(row[0])
    except Exception:
        log.warning("Unreadable cache entry %s; ignoring it", key[:12])
        return MISS


def cache_set(key: str, value: Any, ttl_seconds: float) -> None:
    """Store a value (empty results are skipped, so a transient failure doesn't stick)."""
    if _is_empty(value):
        return
    try:
        text = _encode(value)
        with _get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO market_cache (key, value, expires_at, created_at) "
                "VALUES (%s, %s, now() + make_interval(secs => %s), now()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                "expires_at = EXCLUDED.expires_at, created_at = EXCLUDED.created_at",
                (key, text, float(ttl_seconds)),
            )
            if random.random() < 0.01:  # occasional cleanup of long-expired rows
                conn.execute("DELETE FROM market_cache WHERE expires_at < now() - interval '1 day'")
    except Exception:
        log.warning("Cache write failed; continuing", exc_info=True)


def cached(ttl_seconds: int) -> Callable:
    """Cache a function's result for ttl_seconds, keyed on its (public) arguments."""
    def decorator(fn: Callable) -> Callable:
        namespace = f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = make_key(namespace, args, sorted(kwargs.items()))
            hit = cache_get(key)
            if hit is not MISS:
                return hit
            result = fn(*args, **kwargs)
            cache_set(key, result, ttl_seconds)
            return result
        return wrapper
    return decorator


def clear_cache() -> None:
    with _get_pool().connection() as conn:
        conn.execute("DELETE FROM market_cache")