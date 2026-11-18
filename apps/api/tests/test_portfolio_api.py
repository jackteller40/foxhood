"""Portfolio, value history, CSV import and earnings endpoints, using the fake market in tests/fakes.py.
Fake prices: NVDA $1,150 on 2024-06-03, then a 10-for-1 split on 2024-06-10; live NVDA quote $130."""
from datetime import datetime

import pytest

from datasources import market
from datasources.clients import DataProviderError

NVDA_10 = {"ticker": "NVDA", "purchase_date": "2024-06-03", "shares": 10}


async def test_portfolio_view(client, signed_in):
    headers, _ = await signed_in()
    assert (await client.post("/holdings", headers=headers, json=NVDA_10)).status_code == 201
    data = (await client.get("/portfolio", headers=headers)).json()
    [pos] = data["positions"]
    assert pos["ticker"] == "NVDA" and pos["shares"] == 100.0           # 10 shares became 100 at the split
    assert pos["cost_basis"] == 11500.0 and pos["market_value"] == 13000.0 and pos["weight_pct"] == 100.0
    s = data["summary"]
    assert s["total_value"] == 13000.0 and s["total_pnl"] == 1500.0 and s["benchmark"] == "SPY"
    assert data["sectors"] == [{"sector": "Other", "weight_pct": 100.0}] and data["lot_errors"] == []
    again = (await client.get("/portfolio", headers=headers)).json()
    assert again["as_of"] == data["as_of"]                               # served from the 1-minute cache


async def test_portfolio_cache_sees_new_holdings(client, signed_in):
    headers, _ = await signed_in()
    await client.post("/holdings", headers=headers, json=NVDA_10)
    assert len((await client.get("/portfolio", headers=headers)).json()["positions"]) == 1
    await client.post("/holdings", headers=headers, json={"ticker": "SPY", "purchase_date": "2024-06-04", "amount": 5280})
    assert len((await client.get("/portfolio", headers=headers)).json()["positions"]) == 2


async def test_empty_portfolio_and_privacy(client, signed_in):
    alice, _ = await signed_in()
    bob, _ = await signed_in()
    await client.post("/holdings", headers=alice, json=NVDA_10)
    empty = (await client.get("/portfolio", headers=bob)).json()
    assert empty["summary"] is None and empty["positions"] == []
    assert (await client.get("/portfolio/history", headers=bob)).json()["points"] == []


async def test_value_history(client, signed_in):
    headers, _ = await signed_in()
    await client.post("/holdings", headers=headers, json=NVDA_10)
    data = (await client.get("/portfolio/history?range=all", headers=headers)).json()
    first = data["points"][0]
    assert first == {"date": "2024-06-03", "portfolio": 11500.0, "benchmark": 11500.0, "invested": 11500.0}
    assert (await client.get("/portfolio/history?range=5y", headers=headers)).status_code == 422


async def test_manual_add_rejects_unknown_ticker(client, signed_in):
    headers, _ = await signed_in()
    r = await client.post("/holdings", headers=headers, json={"ticker": "ZZZZQ", "purchase_date": "2024-06-03", "shares": 1})
    assert r.status_code == 422 and "No closing price" in r.json()["detail"]
    assert (await client.get("/holdings", headers=headers)).json() == []


CSV = """Symbol,Purchase Date,Shares,Amount
NVDA,06/03/2024,10,
SPY,2024-06-04,,"$5,280"
ZZZZQ,2024-06-03,1,

NVDA,2999-01-01,1,
NVDA,not-a-date,1,
NVDA,2024-06-03,1,100
"""


async def test_csv_preview_then_commit(client, signed_in):
    headers, _ = await signed_in()
    prev = (await client.post("/holdings/import/preview", headers=headers, json={"csv": CSV})).json()
    assert (prev["ok"], prev["errors"]) == (2, 4)
    rows = {r["row"]: r for r in prev["rows"]}
    assert rows[2]["status"] == "ok" and rows[2]["shares_now"] == 100.0 and rows[2]["price_paid"] == 1150.0
    assert rows[3]["status"] == "ok" and rows[3]["amount"] == 5280.0
    assert "No closing price" in rows[4]["error"]
    assert "future" in rows[6]["error"] and "Unreadable date" in rows[7]["error"]
    assert "exactly one" in rows[8]["error"].lower() or "either" in rows[8]["error"].lower()
    assert (await client.get("/holdings", headers=headers)).json() == []        # preview saves nothing

    good = [{k: r[k] for k in ("ticker", "purchase_date", "shares", "amount")} for r in prev["rows"] if r["status"] == "ok"]
    done = await client.post("/holdings/import/commit", headers=headers, json={"rows": good})
    assert done.status_code == 201 and done.json() == {"created": 2}
    holdings = (await client.get("/holdings", headers=headers)).json()
    assert sorted(h["ticker"] for h in holdings) == ["NVDA", "SPY"] and {h["source"] for h in holdings} == {"csv"}


async def test_csv_commit_is_all_or_nothing(client, signed_in):
    headers, _ = await signed_in()
    rows = [NVDA_10, {"ticker": "ZZZZQ", "purchase_date": "2024-06-03", "shares": 1}]
    r = await client.post("/holdings/import/commit", headers=headers, json={"rows": rows})
    assert r.status_code == 422 and r.json()["detail"]["rows"][0]["ticker"] == "ZZZZQ"
    assert (await client.get("/holdings", headers=headers)).json() == []


@pytest.mark.parametrize("bad_csv", ["", "ticker,shares\nNVDA,1\n"])
async def test_csv_needs_the_right_columns(client, signed_in, bad_csv):
    headers, _ = await signed_in()
    r = await client.post("/holdings/import/preview", headers=headers, json={"csv": bad_csv or " "})
    assert r.status_code == 422


# Shaped like Fidelity's positions export: BOM, cash row, signed dollar values, trailing commas, no dates, footer.
FIDELITY = (
    "\ufeffAccount number,Account name,Symbol,Description,Quantity,Last price,Current value,Cost basis total,Type\r\n"
    "X1,Individual,SPAXX**,HELD IN MONEY MARKET,,,$1.39,,Cash,\r\n"
    "X1,Individual,NVDA,NVIDIA CORPORATION COM,10,$130.00,\"$1,300.00\",\"$1,150.00\",Cash,\r\n"
    "X1,Individual,SPY,SPDR S&P500 ETF TRUST,2,$600.00,+$1200.00,$1054.00,Cash,\r\n"
    "\r\n\"The data and information in this spreadsheet is provided to you solely for your use.\"\r\n"
    "\r\n\"Date downloaded Nov-17-2026 8:45 p.m ET\"\r\n"
)


async def test_csv_broker_positions_export_asks_for_a_date(client, signed_in):
    headers, _ = await signed_in()
    r = await client.post("/holdings/import/preview", headers=headers, json={"csv": FIDELITY})
    assert r.status_code == 422 and r.json()["detail"]["needs_date"] is True

    prev = (await client.post("/holdings/import/preview", headers=headers,
                              json={"csv": FIDELITY, "default_date": "2024-06-04"})).json()
    assert (prev["ok"], prev["errors"]) == (2, 0)
    assert [(s["ticker"], s["row"]) for s in prev["skipped"]] == [("SPAXX", 2)]
    nvda, spy = prev["rows"]
    assert (nvda["row"], nvda["ticker"], nvda["shares"], nvda["broker_cost_basis"]) == (3, "NVDA", 10.0, 1150.0)
    assert spy["purchase_date"] == "2024-06-04" and spy["amount"] is None


@pytest.mark.parametrize("prefix", ["", "Brokerage Account History\n\n"])
async def test_csv_title_lines_above_the_header_are_ignored(client, signed_in, prefix):
    headers, _ = await signed_in()
    prev = (await client.post("/holdings/import/preview", headers=headers,
                              json={"csv": prefix + "Ticker,Date,Shares\nNVDA,2024-06-03,1\n"})).json()
    assert prev["ok"] == 1 and prev["rows"][0]["row"] == (4 if prefix else 2)


async def test_upcoming_earnings(client, signed_in, monkeypatch):
    monkeypatch.setattr(market, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: datetime(2026, 11, 17, 9, tzinfo=tz))}))
    headers, _ = await signed_in()
    await client.post("/holdings", headers=headers, json=NVDA_10)
    await client.post("/watchlist", headers=headers, json={"ticker": "AAPL"})
    data = (await client.get("/earnings/upcoming", headers=headers)).json()
    assert data["tickers"] == ["AAPL", "NVDA"] and [e["ticker"] for e in data["earnings"]] == ["AAPL", "NVDA"]


async def test_provider_outage_is_a_503(client, signed_in, monkeypatch):
    headers, _ = await signed_in()

    def down(*a, **k):
        raise DataProviderError("Price data is temporarily rate-limited (Tiingo free tier). Try again shortly.")

    monkeypatch.setattr(market, "tiingo_get", down)
    r = await client.post("/holdings", headers=headers, json={"ticker": "AMD", "purchase_date": "2024-06-03", "shares": 1})
    assert r.status_code == 503 and "rate-limited" in r.json()["detail"]
