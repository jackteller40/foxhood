import uuid

import pytest
from fastapi import HTTPException

from app import rate_limit


def test_limit_and_window():
    rate_limit.reset()
    uid, other = uuid.uuid4(), uuid.uuid4()
    for i in range(rate_limit.LIMIT):
        rate_limit.check(uid, now=1000 + i * 0.1)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check(uid, now=1010)
    assert exc.value.status_code == 429 and int(exc.value.headers["Retry-After"]) >= 1
    rate_limit.check(other, now=1010)                         # other people aren't affected
    rate_limit.check(uid, now=1000 + rate_limit.WINDOW + 1)   # a minute later, allowed again


async def test_api_returns_429(client, signed_in, monkeypatch):
    rate_limit.reset()
    headers, _ = await signed_in()                             # signing in used one request
    monkeypatch.setattr(rate_limit, "LIMIT", 3)
    assert [(await client.get("/me", headers=headers)).status_code for _ in range(3)] == [200, 200, 429]
