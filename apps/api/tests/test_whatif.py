"""What-if simulations: before/after weights, cash, realized gain, past-year comparison, bad input."""
from datetime import date, timedelta

import pandas as pd
import pytest

from agent.tools import make_local_tools
from portfolio.whatif import Change, simulate
from tests.fakes import bar

TODAY = date.today()


def year_of(start: float, end: float, wobble: float = 0.0) -> list[dict]:
    """About a year of weekday bars drifting from start to end, ending yesterday."""
    days = [TODAY - timedelta(days=i) for i in range(370, 0, -1)]
    days = [d for d in days if d.weekday() < 5]
    n = len(days)
    return [bar(d.isoformat(), start + (end - start) * i / (n - 1) + (wobble if i % 2 else -wobble))
            for i, d in enumerate(days)]


@pytest.fixture
def market_year(fake_market):
    fake_market["histories"].update(NVDA=year_of(80.0, 130.0, wobble=2.0), SPY=year_of(500.0, 600.0),
                                    VOO=year_of(460.0, 550.0))
    fh = fake_market["finnhub"]
    fh.quotes.update(NVDA={"c": 130.0, "pc": 128.0}, SPY={"c": 600.0, "pc": 598.0}, VOO={"c": 550.0, "pc": 549.0})
    fh.types["VOO"] = "ETP"
    return fake_market


def positions() -> pd.DataFrame:
    """100 NVDA bought for $8,000, now $13,000."""
    return pd.DataFrame([{"ticker": "NVDA", "sector": "Technology", "shares": 100.0, "price": 130.0,
                          "cost_basis": 8000.0}])


def test_sell_half_then_buy_with_the_cash(market_year):
    r = simulate(positions(), [Change("NVDA", "sell", fraction=0.5), Change("VOO", "buy", amount_usd=5500)], TODAY)
    sell, buy = r["changes"]
    assert sell["shares"] == 50 and sell["proceeds"] == 6500 and sell["realized_gain_estimate"] == 2500
    assert buy["shares"] == 10 and buy["paid_from_cash"] == 5500 and r["new_money_added"] == 0
    after = r["after"]
    assert after["cash"] == pytest.approx(1000) and after["total_value"] == pytest.approx(13000)
    assert {p["ticker"]: round(p["weight_pct"], 1) for p in after["positions"]} == {"NVDA": 50.0, "VOO": 42.3}
    assert after["sector_mix_pct"]["ETF"] == pytest.approx(5500 / 13000 * 100)
    assert r["before"]["largest_weight_pct"] == 100

    year = r["past_year"]
    assert year["current_holdings"]["return_pct"] > year["after_change"]["return_pct"] > 0   # NVDA ran harder
    assert year["current_holdings"]["volatility_pct"] > year["after_change"]["volatility_pct"]  # and swung more
    assert year["spy"]["return_pct"] == pytest.approx(20, abs=0.5)


def test_buy_with_new_money(market_year):
    r = simulate(positions(), [Change("VOO", "buy", shares=2)], TODAY)
    assert r["new_money_added"] == 1100 and r["after"]["cash"] == 0 and r["realized_gain_estimate"] == 0


@pytest.mark.parametrize("change, message", [
    (Change("AAPL", "sell", shares=1), "don't hold AAPL"),
    (Change("NVDA", "sell", shares=500), "can't sell"),
    (Change("NVDA", "sell", fraction=1.5), "between 0 and 1"),
    (Change("NVDA", "sell", shares=1, fraction=0.5), "exactly one"),
    (Change("VOO", "buy", fraction=0.5), "only applies to sells"),
    (Change("NVDA", "hold", shares=1), "buy or sell"),
])
def test_impossible_changes_are_explained(market_year, change, message):
    with pytest.raises(ValueError, match=message):
        simulate(positions(), [change], TODAY)


async def test_tool_on_a_real_portfolio(client, signed_in, market_year):
    headers, repo = await signed_in()
    start = market_year["histories"]["NVDA"][0]["date"][:10]
    assert (await client.post("/holdings", headers=headers,
                              json={"ticker": "NVDA", "purchase_date": start, "shares": 10})).status_code == 201
    tool = next(t for t in make_local_tools(repo.user_id) if t.name == "simulate_portfolio_change")
    out = await tool.ainvoke({"changes": [{"ticker": "nvda", "action": "Sell", "fraction": 0.5}]})
    assert '"proceeds": 650.0' in out and '"cash": 650.0' in out and "nothing was changed" in out
    assert "don't hold" in await tool.ainvoke({"changes": [{"ticker": "AAPL", "action": "sell", "shares": 1}]})
    assert (await client.get("/holdings", headers=headers)).json()[0]["shares"] == 10        # really unchanged
