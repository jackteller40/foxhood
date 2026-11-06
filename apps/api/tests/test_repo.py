from datetime import date, timedelta

import pytest

from db.repo import AdminRepo


async def test_holding_validation(make_user):
    u = await make_user()
    with pytest.raises(ValueError):
        await u.add_holding("NVDA", date(2024, 6, 3), shares=1, amount=100)   # both
    with pytest.raises(ValueError):
        await u.add_holding("NVDA", date(2024, 6, 3))                          # neither
    with pytest.raises(ValueError):
        await u.add_holding("NVDA", date.today() + timedelta(days=3), shares=1)  # future
    with pytest.raises(ValueError):
        await u.add_holding("NV DA", date(2024, 6, 3), shares=1)               # bad ticker
    h = await u.add_holding(" nvda ", date(2024, 6, 3), shares=10)
    assert h.ticker == "NVDA" and h.to_lot().shares == 10


async def test_watchlist_dedupes_and_keeps_note(make_user):
    u = await make_user()
    first, created = await u.add_to_watchlist("amd", "AI chip competitor")
    again, created_again = await u.add_to_watchlist("AMD", "overwrite attempt")
    assert created and not created_again
    assert again.note == "AI chip competitor"
    assert await u.remove_from_watchlist("amd") is True
    assert await u.list_watchlist() == []


async def test_memory_search(make_user):
    u = await make_user()
    await u.add_memory("preference", "Does not want oil or tobacco stocks recommended.", ["exclusions", "oil"])
    await u.add_memory("fact", "Rebalances once a year to 70/30.", ["allocation"])
    assert (await u.search_memories("Any good oil stocks to buy?"))[0][1].content.startswith("Does not want oil")
    assert len(await u.search_memories("risk limits preferences goals")) == 1  # matches the kind
    assert await u.search_memories("What's the weather in Paris?") == []


async def test_profile_validation_and_defaults(make_user):
    u = await make_user()
    p = await u.get_profile()
    assert p["risk_tolerance"] == "medium" and p["interests"] == []
    with pytest.raises(ValueError):
        await u.update_profile(risk_tolerance="extreme")
    with pytest.raises(ValueError):
        await u.update_profile(is_admin=True)  # not a profile field
    p = await u.update_profile(interests=["AI", " dividends ", ""])
    assert p["interests"] == ["AI", "dividends"]


async def test_invites(session):
    admin = AdminRepo(session)
    await admin.invite("Friend@Example.com")
    assert await admin.is_invited("friend@example.com")
    await admin.revoke("friend@example.com")
    assert not await admin.is_invited("friend@example.com")
    await admin.invite("friend@example.com")  # re-invite restores access
    assert await admin.is_invited("friend@example.com")