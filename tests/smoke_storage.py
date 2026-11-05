"""Run from the repo root:  python -m tests.smoke_storage   (rebuilds app.db with demo data)"""
from __future__ import annotations

import traceback
import uuid
from datetime import date

from portfolio import metrics
from portfolio.positions import resolve_lot
from storage import db
from storage.seed_demo import seed

results: list[tuple[str, str]] = []


def check(name, fn):
    print(f"\n=== {name} ===")
    try:
        fn()
        results.append((name, "PASS"))
    except Exception:
        traceback.print_exc()
        results.append((name, "FAIL"))


def users():
    return db.list_users()  # ordered by id: Alex, Priya, Dan


def seeding():
    ids = seed(reset=True)
    for u in users():
        print(u["id"], u["name"], "|", u["persona"], "|", u["risk_tolerance"], "|", u["interests"])
    assert len(ids) == 3


def holdings_roundtrip():
    for u in users():
        resolved = [resolve_lot(l) for l in db.holdings_as_lots(u["id"])]
        s = metrics.portfolio_summary(resolved)
        print(f"{u['name']:12} value ${s['total_value']:,.0f} | largest {s['largest_position']} {s['largest_weight_pct']:.0f}%")
        print(f"{'':12} price return {s['total_pnl_pct']:6.1f}% vs SPY {s['benchmark_pnl_pct']:6.1f}%  "
              f"(gap {s['excess_return_pct']:+.1f})")
        print(f"{'':12} total return {s['total_return_pct']:6.1f}% vs SPY {s['benchmark_total_return_pct']:6.1f}%  "
              f"(gap {s['excess_total_return_pct']:+.1f})")


def schd_split():
    # SCHD did a 3-for-1 split in Oct 2024; Dan's dollar-amount lot from 2022 should show split x3
    dan = users()[2]
    lot = next(l for l in db.holdings_as_lots(dan["id"]) if l.ticker == "SCHD")
    r = resolve_lot(lot)
    print(f"paid ${r.price_paid:,.2f} | split x{r.split_factor:g} | "
          f"bought {r.shares_bought:,.2f} -> now {r.shares_now:,.2f} | cost ${r.cost_basis:,.2f}")
    assert r.split_factor == 3.0, f"expected x3, got x{r.split_factor}"


def watchlist_ops():
    uid = users()[0]["id"]
    before = len(db.list_watchlist(uid))
    db.add_to_watchlist(uid, "amd", "duplicate test")      # existing ticker, lowercase
    assert len(db.list_watchlist(uid)) == before, "duplicate ticker created a new row"
    db.add_to_watchlist(uid, "ARM")
    assert len(db.list_watchlist(uid)) == before + 1
    assert db.remove_from_watchlist(uid, "ARM")
    print([(w["ticker"], w["note"]) for w in db.list_watchlist(uid)])


def memory_search():
    alex, priya, dan = users()
    cases = [
        (alex, "Is my portfolio too concentrated in one position?", True),
        (dan, "Any good oil stocks to buy?", True),
        (priya, "Should I pick individual stocks?", True),
        (alex, "What's the weather in Paris?", False),
    ]
    for u, q, expect_hit in cases:
        hits = db.search_memories(u["id"], q)
        print(f"{u['name']:12} | {q}\n    -> {[(h['score'], h['content']) for h in hits]}")
        assert bool(hits) == expect_hit, f"unexpected result for: {q}"


def briefs_roundtrip():
    uid = users()[0]["id"]
    today = date.today()
    db.save_brief(uid, today, "close", "# v1", run_id="test-run-1")
    db.save_brief(uid, today, "close", "# v2", run_id="test-run-2")  # same key: should overwrite
    b = db.get_brief(uid, today, "close")
    print(b)
    assert b["content_md"] == "# v2" and b["run_id"] == "test-run-2"
    assert db.get_brief(uid, today, "premarket") is None
    try:
        db.save_brief(uid, today, "lunch", "x")
        raise AssertionError("bad session accepted")
    except ValueError as e:
        print("bad session rejected:", e)


def trace_roundtrip():
    uid = users()[0]["id"]
    root, sub = str(uuid.uuid4()), str(uuid.uuid4())
    db.log_trace_event(run_id=root, root_run_id=root, event_type="run", name="post_close_recap",
                       user_id=uid, input={"session": "close"})
    db.log_trace_event(run_id=str(uuid.uuid4()), parent_run_id=root, root_run_id=root, event_type="tool",
                       name="get_portfolio_summary", user_id=uid, input={"user_id": uid},
                       output={"total_value": 40624.12}, duration_ms=120.5)
    db.log_trace_event(run_id=sub, parent_run_id=root, root_run_id=root, event_type="subagent",
                       name="news_analyst", user_id=uid, input={"tickers": ["NVDA"]})
    db.log_trace_event(run_id=str(uuid.uuid4()), parent_run_id=root, root_run_id=root,
                       event_type="permission", name="place_trade", user_id=uid,
                       status="denied", output={"reason": "trading is never allowed"})
    events = db.get_run_events(root)
    for e in events:
        print(f"{e['event_type']:10} {e['name']:22} {e['status']:7} parent={(e['parent_run_id'] or '-')[:8]}")
    assert len(events) == 4
    print(db.list_runs(uid, limit=3))


def validation():
    uid = users()[0]["id"]
    for label, fn in [
        ("both shares + amount", lambda: db.add_holding(uid, "AAPL", date(2024, 1, 3), shares=1, amount=100)),
        ("bad memory kind", lambda: db.add_memory(uid, "gossip", "x")),
        ("bad risk level", lambda: db.create_user("Test", "extreme")),
        ("bad event type", lambda: db.log_trace_event(run_id="x", root_run_id="x", event_type="vibes", name="x")),
    ]:
        try:
            fn()
            raise AssertionError(f"{label} was accepted")
        except ValueError as e:
            print(f"{label} -> {e}")


if __name__ == "__main__":
    for name, fn in [
        ("seeding", seeding),
        ("holdings -> portfolio math", holdings_roundtrip),
        ("SCHD split (dollar-amount lot)", schd_split),
        ("watchlist", watchlist_ops),
        ("memory search", memory_search),
        ("briefs", briefs_roundtrip),
        ("traces", trace_roundtrip),
        ("validation", validation),
    ]:
        check(name, fn)

    print("\n=== SUMMARY ===")
    for name, status in results:
        print(f"{status:5} {name}")