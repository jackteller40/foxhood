"""Isolation: one user must never see, change, or delete another user's data, and the database
must never hold readable financial data. If any of these fail, nothing ships."""
from datetime import date

import pytest
from sqlalchemy import func, select, text

from db.crypto import DecryptionError
from db.models import Holding, Memory, User, WatchlistItem
from db.repo import NotFound


async def test_holdings_are_private(make_user):
    alice, bob = await make_user(), await make_user()
    h = await alice.add_holding("NVDA", date(2024, 6, 3), shares=10)
    assert await bob.list_holdings() == []
    with pytest.raises(NotFound):
        await bob.get_holding(h.id)
    with pytest.raises(NotFound):
        await bob.delete_holding(h.id)
    assert [x.id for x in await alice.list_holdings()] == [h.id]  # untouched


async def test_watchlist_is_private(make_user):
    alice, bob = await make_user(), await make_user()
    w, _ = await alice.add_to_watchlist("AMD", "chip competitor")
    assert await bob.list_watchlist() == []
    assert await bob.remove_from_watchlist("AMD") is False
    with pytest.raises(NotFound):
        await bob.delete_watch_item(w.id)
    assert [x.ticker for x in await alice.list_watchlist()] == ["AMD"]


async def test_memories_are_private(make_user):
    alice, bob = await make_user(), await make_user()
    m = await alice.add_memory("preference", "Never recommend oil stocks", ["oil"])
    assert await bob.list_memories() == []
    assert await bob.search_memories("oil stocks") == []
    with pytest.raises(NotFound):
        await bob.delete_memory(m.id)
    assert len(await alice.list_memories()) == 1


async def test_profiles_are_private(make_user):
    alice, bob = await make_user(), await make_user()
    await alice.update_profile(name="Alice", risk_tolerance="high")
    await bob.update_profile(name="Bob", risk_tolerance="low")
    assert (await alice.get_profile())["name"] == "Alice"
    assert (await alice.get_profile())["risk_tolerance"] == "high"


async def test_export_contains_only_own_data(make_user):
    alice, bob = await make_user(), await make_user()
    await alice.add_holding("NVDA", date(2024, 6, 3), shares=10)
    await bob.add_holding("KO", date(2021, 9, 1), shares=40)
    data = await alice.export()
    assert [h["ticker"] for h in data["holdings"]] == ["NVDA"]
    assert "KO" not in str(data)


async def test_database_holds_no_readable_data(make_user, session):
    alice = await make_user()
    await alice.update_profile(name="Alice Example", interests=["semiconductors"])
    await alice.add_holding("NVDA", date(2024, 6, 3), shares=10)
    await alice.add_to_watchlist("TSM", "foundry exposure")
    await alice.add_memory("preference", "Never recommend oil stocks", ["exclusions"])
    rows = await session.execute(text(
        "SELECT u.profile_enc, h.payload_enc, w.payload_enc, m.payload_enc FROM users u "
        "JOIN holdings h ON h.user_id = u.id JOIN watchlist w ON w.user_id = u.id "
        "JOIN memories m ON m.user_id = u.id WHERE u.id = :id"), {"id": alice.user_id})
    raw = " ".join(str(v) for row in rows for v in row)
    for secret in ["Alice Example", "semiconductors", "NVDA", "foundry exposure", "Never recommend", "exclusions"]:
        assert secret not in raw


async def test_ciphertext_copied_between_users_fails(make_user, session):
    """Someone with database access copies Alice's encrypted holding into Bob's row: it must not decrypt."""
    alice, bob = await make_user(), await make_user()
    a = await alice.add_holding("NVDA", date(2024, 6, 3), shares=10)
    b = await bob.add_holding("KO", date(2021, 9, 1), shares=40)
    await session.execute(
        text("UPDATE holdings SET payload_enc = (SELECT payload_enc FROM holdings WHERE id = :a) WHERE id = :b"),
        {"a": a.id, "b": b.id})
    await session.commit()
    session.expire_all()  # drop cached objects so the next read hits the database
    with pytest.raises(DecryptionError):
        await bob.list_holdings()


async def test_delete_account_removes_everything(make_user, session):
    alice, bob = await make_user(), await make_user()
    await alice.add_holding("NVDA", date(2024, 6, 3), shares=10)
    await alice.add_to_watchlist("AMD")
    await alice.add_memory("fact", "Saving for a house")
    await bob.add_holding("KO", date(2021, 9, 1), shares=40)
    uid = alice.user_id

    await alice.delete_account()

    for model in (Holding, WatchlistItem, Memory):
        q = select(func.count()).select_from(model).where(model.user_id == uid)
        assert (await session.execute(q)).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(User).where(User.id == uid))).scalar_one() == 0
    assert len(await bob.list_holdings()) == 1  # nobody else affected