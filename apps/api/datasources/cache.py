"""Tiny on-disk cache so repeated API calls (and Streamlit reruns) dont burn rate limits"""
from __future__ import annotations

import functools
import hashlib
import pickle
import shutil
import time
from typing import Any, Callable

import pandas as pd
from core.config import settings

def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return value.empty
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False

def cached(ttl_seconds: int) -> Callable:
    """Cache a function's result on a disk for ttl_seconds, keyed on its arguments.
    Empty results are not cached, so a transient API failure doesn't stick."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            raw_key = f"{fn.__module__}.{fn.__qualname__}|{args!r}|{sorted(kwargs.items())!r}"
            key = hashlib.sha256(raw_key.encode()).hexdigest()[:32]
            path = settings.cache_dir / f"{key}.pkl"
            
            if path.exists() and time.time() - path.stat().st_mtime < ttl_seconds:
                try:
                    with path.open("rb") as f:
                        return pickle.load(f)
                except Exception:
                    path.unlink(missing_ok=True)
            
            result = fn(*args, **kwargs)
            if not _is_empty(result):
                settings.cache_dir.mkdir(exist_ok=True)
                with path.open("wb") as f:
                    pickle.dump(result, f)
            return result
        return wrapper
    return decorator

def clear_cache() -> None:
    shutil.rmtree(settings.cache_dir, ignore_errors=True)