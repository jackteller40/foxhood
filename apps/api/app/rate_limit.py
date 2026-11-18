"""Per-user request limit, kept in memory. Each Cloud Run instance counts on its own (there are at most 3),
which is plenty to stop a stuck browser tab or a script from hammering the API. AI cost has its own daily caps."""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException, status

LIMIT = 60          # requests
WINDOW = 60.0       # seconds

_hits: dict[uuid.UUID, deque[float]] = defaultdict(deque)


def check(user_id: uuid.UUID, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    hits = _hits[user_id]
    while hits and hits[0] <= now - WINDOW:
        hits.popleft()
    if len(hits) >= LIMIT:
        retry = max(1, int(hits[0] + WINDOW - now) + 1)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many requests at once. Wait a moment and try again.",
                            headers={"Retry-After": str(retry)})
    hits.append(now)
    if len(_hits) > 5000:   # tiny app; never let the table grow without bound
        for uid in [u for u, h in _hits.items() if not h or h[-1] <= now - WINDOW]:
            del _hits[uid]


def reset() -> None:
    _hits.clear()
