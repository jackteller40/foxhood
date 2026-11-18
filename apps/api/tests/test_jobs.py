"""Scheduled jobs (morning briefs, alerts), their endpoints, alert and settings endpoints.
Uses the fake market (tests/fakes.py): NVDA bought 2024-06-03 at $1,150; live quote set per test."""
from dataclasses import replace
from datetime import datetime

import pytest

from app.routes import jobs as job_routes
from datasources import market
from datasources.market import ET
from jobs.alerts import alert_message, check_user, run_alerts
from jobs.morning_briefs import run_morning_briefs
from tests.test_agent import ScriptedModel, say

WED = datetime(2026, 11, 18, 11, 0, tzinfo=ET)    # a trading day; the next one is Thu Nov 19
SAT = datetime(2026, 11, 21, 11, 0, tzinfo=ET)
NVDA_10 = {"ticker": "NVDA", "purchase_date": "2024-06-03", "shares": 10}


@pytest.fixture
def on_wednesday(monkeypatch):
    """The earnings calendar looks at 'today'; pin it to WED so NVDA's Nov 19 report is 'tomorrow'."""
    monkeypatch.setattr(market, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: WED)}))


async def test_alert_rules_fire_once_per_day(client, signed_in, fake_market, on_wednesday):
    headers, repo = await signed_in()
    await client.post("/holdings", headers=headers, json=NVDA_10)
    fake_market["finnhub"].quotes["NVDA"] = {"c": 130.0, "pc": 120.0}      # +8.3% today
    await repo.update_settings(max_position_pct=25)

    assert await check_user(repo.user_id, WED) == 3
    alerts = {a.kind: a for a in await repo.list_alerts(WED.date())}
    assert set(alerts) == {"big_move", "position_limit", "earnings_tomorrow"}
    assert alert_message("big_move", "NVDA", alerts["big_move"].data, WED) == "NVDA is up 8.3% today."
    assert alert_message("position_limit", "NVDA", alerts["position_limit"].data, WED) == (
        "NVDA is 100% of your portfolio, over the 25% limit you set.")
    assert alert_message("earnings_tomorrow", "NVDA", alerts["earnings_tomorrow"].data, WED) == (
        "NVDA reports earnings tomorrow after the close. Analysts expect $1.25 a share.")

    assert await check_user(repo.user_id, WED) == 0                         # same day: nothing new
    await repo.dismiss_alert(alerts["big_move"].id)
    assert await check_user(repo.user_id, WED) == 0                         # dismissed stays dismissed


async def test_quiet_day_raises_nothing(client, signed_in, on_wednesday, fake_market):
    headers, repo = await signed_in()
    fake_market["finnhub"].calendar = []
    await client.post("/holdings", headers=headers, json=NVDA_10)            # +1.6% today, no limit set
    assert await check_user(repo.user_id, WED) == 0
    assert (await run_alerts(SAT, user_ids=[repo.user_id]))["ran"] is False


async def test_alerts_endpoint_and_dismiss(client, signed_in):
    headers, repo = await signed_in()
    other_headers, _ = await signed_in()
    today = datetime.now(ET).date()
    [a] = await repo.add_alerts(today, [("big_move", "NVDA", {"pct": -6.2, "day_pnl": -80.0})])
    [out] = (await client.get("/alerts", headers=headers)).json()
    assert out["message"] == "NVDA is down 6.2% today." and out["kind"] == "big_move"
    assert (await client.get("/alerts", headers=other_headers)).json() == []
    assert (await client.post(f"/alerts/{a.id}/dismiss", headers=other_headers)).status_code == 404
    assert (await client.post(f"/alerts/{a.id}/dismiss", headers=headers)).status_code == 204
    assert (await client.get("/alerts", headers=headers)).json() == []


async def test_settings_endpoint(client, signed_in):
    headers, _ = await signed_in()
    s = (await client.get("/me/settings", headers=headers)).json()
    assert s == {"scheduled_briefs": True, "email_briefs": True, "email_alerts": True, "max_position_pct": None}
    s = (await client.patch("/me/settings", headers=headers, json={"email_briefs": False, "max_position_pct": 25})).json()
    assert s["email_briefs"] is False and s["max_position_pct"] == 25 and s["scheduled_briefs"] is True
    s = (await client.patch("/me/settings", headers=headers, json={"max_position_pct": None})).json()
    assert s["max_position_pct"] is None and s["email_briefs"] is False
    assert (await client.patch("/me/settings", headers=headers, json={"max_position_pct": 500})).status_code == 422


async def test_morning_briefs_job(client, signed_in):
    headers, repo = await signed_in()
    _, empty_repo = await signed_in()                                        # no holdings: skipped
    await client.post("/holdings", headers=headers, json=NVDA_10)
    model = ScriptedModel(responses=[say("Good morning. Futures are flat. Not financial advice.")])

    result = await run_morning_briefs(WED, model=model, use_mcp=False, user_ids=[repo.user_id, empty_repo.user_id])
    assert result["outcomes"] == {"written": 1, "no holdings": 1}
    assert "Futures are flat" in (await repo.get_brief(WED.date(), "premarket")).content

    again = await run_morning_briefs(WED, model=model, use_mcp=False, user_ids=[repo.user_id])
    assert again["outcomes"] == {"already written": 1}                       # no second AI call
    assert (await run_morning_briefs(SAT, user_ids=[repo.user_id]))["ran"] is False

    await empty_repo.update_settings(scheduled_briefs=False)
    off = await run_morning_briefs(WED, model=model, use_mcp=False, user_ids=[empty_repo.user_id])
    assert off["outcomes"] == {"turned off": 1}


async def test_job_endpoints_need_the_key(client, monkeypatch):
    assert (await client.post("/jobs/alerts")).status_code == 503            # JOBS_SECRET unset: off
    monkeypatch.setattr(job_routes, "settings", replace(job_routes.settings, jobs_secret="k" * 32))
    assert (await client.post("/jobs/alerts")).status_code == 401
    assert (await client.post("/jobs/alerts", headers={"X-Job-Key": "wrong"})).status_code == 401


@pytest.fixture
def outbox(monkeypatch):
    """Turns email on with a fake Resend: every message lands in this list instead of being sent."""
    from notify import email
    sent: list[dict] = []
    monkeypatch.setattr(email, "settings", replace(email.settings, resend_api_key="re_test", app_url="https://foxhood.app"))
    monkeypatch.setattr(email, "_post", sent.append)
    return sent


async def test_brief_is_emailed_when_written(client, signed_in, outbox):
    headers, repo = await signed_in()
    await client.post("/holdings", headers=headers, json=NVDA_10)
    model = ScriptedModel(responses=[say("**NVDA** reports Thursday. S&P futures flat. <script>x</script>")])
    result = await run_morning_briefs(WED, model=model, use_mcp=False, user_ids=[repo.user_id])
    assert result["emailed"] == 1
    [msg] = outbox
    assert msg["to"] == [(await repo.get_profile())["email"]] and msg["subject"] == "Your morning brief for Wednesday, November 18"
    assert "<strong>NVDA</strong>" in msg["html"] and "<script>" not in msg["html"]       # markdown yes, raw HTML no
    assert "https://foxhood.app/settings" in msg["html"] and "Not financial advice" in msg["html"]

    await run_morning_briefs(WED, model=model, use_mcp=False, user_ids=[repo.user_id])
    assert len(outbox) == 1                                                       # already written: no second email


async def test_new_alerts_are_emailed_once(client, signed_in, fake_market, on_wednesday, outbox):
    headers, repo = await signed_in()
    await client.post("/holdings", headers=headers, json=NVDA_10)
    fake_market["finnhub"].quotes["NVDA"] = {"c": 130.0, "pc": 120.0}
    fake_market["finnhub"].calendar = []
    assert await check_user(repo.user_id, WED) == 1
    assert [m["subject"] for m in outbox] == ["NVDA is up 8.3% today."]
    assert await check_user(repo.user_id, WED) == 0 and len(outbox) == 1


async def test_email_switches_are_respected(client, signed_in, fake_market, on_wednesday, outbox):
    headers, repo = await signed_in()
    await client.post("/holdings", headers=headers, json=NVDA_10)
    await repo.update_settings(email_briefs=False, email_alerts=False, max_position_pct=10)
    model = ScriptedModel(responses=[say("Morning. Not financial advice.")])
    assert (await run_morning_briefs(WED, model=model, use_mcp=False, user_ids=[repo.user_id]))["emailed"] == 0
    assert await check_user(repo.user_id, WED) >= 1
    assert outbox == []
