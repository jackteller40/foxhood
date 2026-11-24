"""Admin endpoints: admins only, metadata only, invites from the browser, job run history."""
import json

import pytest

from db.repo import AdminRepo
from jobs.record import recorded


@pytest.fixture
def admin_user(signed_in, session):
    async def _make():
        headers, repo = await signed_in()
        await AdminRepo(session).set_admin((await repo.get_profile())["email"])
        return headers, repo
    return _make


async def test_admin_only(client, signed_in):
    headers, _ = await signed_in()
    for path in ("/admin/overview", "/admin/runs", "/admin/jobs"):
        assert (await client.get(path, headers=headers)).status_code == 403
    assert (await client.post("/admin/invites", headers=headers, json={"email": "x@example.com"})).status_code == 403


async def test_overview_shows_people_and_spend_but_no_content(client, admin_user, signed_in):
    headers, _ = await admin_user()
    friend_headers, friend = await signed_in()
    await friend.add_memory("fact", "My secret plan is to buy NVDA", ["plan"])
    await friend.add_usage("run-1", "claude-haiku-5-5", 1000, 100, 0.0123)
    data = (await client.get("/admin/overview", headers=headers)).json()
    me = next(p for p in data["people"] if p["is_admin"])
    them = next(p for p in data["people"] if p["spent_today_usd"] == pytest.approx(0.0123))
    assert me["status"] == "active" and them["status"] == "active" and data["cap_total_usd"] > 0
    assert "secret plan" not in json.dumps(data)


async def test_invite_and_revoke_from_the_page(client, admin_user):
    headers, _ = await admin_user()
    assert (await client.post("/admin/invites", headers=headers, json={"email": "New.Friend@Gmail.com"})).status_code == 201
    people = (await client.get("/admin/overview", headers=headers)).json()["people"]
    assert next(p for p in people if p["email"] == "new.friend@gmail.com")["status"] == "invited"
    assert (await client.post("/admin/invites/revoke", headers=headers, json={"email": "new.friend@gmail.com"})).status_code == 200
    people = (await client.get("/admin/overview", headers=headers)).json()["people"]
    assert next(p for p in people if p["email"] == "new.friend@gmail.com")["status"] == "revoked"
    assert (await client.post("/admin/invites/revoke", headers=headers, json={"email": "nobody@x.com"})).status_code == 404


async def test_cannot_revoke_yourself(client, admin_user, session):
    headers, repo = await admin_user()
    email = (await repo.get_profile())["email"]
    r = await client.post("/admin/invites/revoke", headers=headers, json={"email": email})
    assert r.status_code == 400


async def test_runs_show_metadata_and_cost(client, admin_user):
    from tests.test_agent import run, say
    headers, repo = await admin_user()
    result, _ = await run(repo, "What do I own?", [say("", ("get_positions", {})), say("Nothing yet. Not financial advice.")])
    runs = (await client.get("/admin/runs", headers=headers)).json()
    mine = next(r for r in runs if r["run_id"] == result.run_id)
    assert mine["task"] and mine["status"] == "ok" and mine["tool_calls"] == 1 and mine["cost_usd"] >= 0
    assert "What do I own" not in json.dumps(runs) and "Nothing yet" not in json.dumps(runs)


async def test_job_runs_are_recorded(client, admin_user, monkeypatch):
    headers, _ = await admin_user()

    async def fine():
        return {"ran": True, "outcomes": {"written": 2}}

    async def broken():
        raise RuntimeError("boom")

    assert (await recorded("briefs", fine))["ran"] is True
    with pytest.raises(RuntimeError):
        await recorded("alerts", broken)
    jobs = (await client.get("/admin/jobs", headers=headers)).json()
    latest = {j["job"]: j for j in reversed(jobs)}
    assert latest["briefs"]["ok"] is True and latest["briefs"]["summary"]["outcomes"] == {"written": 2}
    assert latest["alerts"]["ok"] is False and latest["alerts"]["summary"] == {"error": "RuntimeError"}
    assert latest["alerts"]["finished_at"] is not None
