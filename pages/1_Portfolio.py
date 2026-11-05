import streamlit as st

st.set_page_config(page_title="Portfolio", page_icon="💼", layout="wide")

from datetime import date

import plotly.express as px

from portfolio import metrics
from portfolio.positions import Lot, resolve_lot
from storage import db
from ui.common import flash, sidebar

user = sidebar()
uid = user["id"]


@st.cache_data(ttl=120, show_spinner="Pricing your portfolio...")
def load_portfolio(user_id: int) -> dict:
    lots, errors = [], []
    for h in db.list_holdings(user_id):
        try:
            lots.append((h["id"], resolve_lot(Lot(h["ticker"], h["purchase_date"], shares=h["shares"], amount=h["amount"]))))
        except Exception as e:
            errors.append(f"{h['ticker']} bought {h['purchase_date']}: {e}")
    resolved = [r for _, r in lots]
    if not resolved:
        return {"lots": lots, "errors": errors}
    positions = metrics.positions_table(resolved)
    return {"lots": lots, "errors": errors, "positions": positions,
            "summary": metrics.portfolio_summary(resolved, positions),
            "history": metrics.value_history(resolved),
            "sectors": metrics.sector_exposure(positions)}


def pct(v):
    return "n/a" if v is None else f"{v:+.2f}%"


st.title("Portfolio")
flash()
data = load_portfolio(uid)
for err in data["errors"]:
    st.warning(err)

if "summary" in data:
    s = data["summary"]
    c = st.columns(4)
    c[0].metric("Market value", f"${s['total_value']:,.0f}", f"{s['day_pnl']:+,.0f} today")
    vs_spy = (None if s.get("day_change_pct") is None or s.get("benchmark_day_change_pct") is None
              else s["day_change_pct"] - s["benchmark_day_change_pct"])
    c[1].metric("Today", pct(s.get("day_change_pct")), None if vs_spy is None else f"{vs_spy:+.2f} pts vs SPY")
    c[2].metric("Price return", f"{s['total_pnl_pct']:+.1f}%", f"{s['excess_return_pct']:+.1f} pts vs SPY")
    c[3].metric("Total return (with dividends)", f"{s['total_return_pct']:+.1f}%",
                f"{s['excess_total_return_pct']:+.1f} pts vs SPY")

    st.subheader("Positions")
    cols = ["ticker", "name", "sector", "shares", "avg_cost", "price", "market_value", "weight_pct",
            "pnl_pct", "total_return_pct", "day_change_pct", "day_pnl"]
    st.dataframe(
        data["positions"][cols], hide_index=True, use_container_width=True,
        column_config={
            "shares": st.column_config.NumberColumn("Shares", format="%.2f"),
            "avg_cost": st.column_config.NumberColumn("Avg cost", format="$%.2f"),
            "price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "market_value": st.column_config.NumberColumn("Value", format="$%.0f"),
            "weight_pct": st.column_config.ProgressColumn("Weight", format="%.1f%%", min_value=0, max_value=100),
            "pnl_pct": st.column_config.NumberColumn("Price return", format="%.1f%%"),
            "total_return_pct": st.column_config.NumberColumn("Total return", format="%.1f%%"),
            "day_change_pct": st.column_config.NumberColumn("Today", format="%.2f%%"),
            "day_pnl": st.column_config.NumberColumn("Today $", format="$%.0f"),
        },
    )

    left, right = st.columns([3, 1])
    with left:
        st.subheader("Value over time")
        hist = data["history"].copy()
        hist.index.name = "date"
        hist = hist.rename(columns={"portfolio": "Your portfolio", "benchmark": "Same dollars in SPY",
                                    "invested": "Dollars invested"})
        long = hist.reset_index().melt(id_vars="date", var_name="series", value_name="value")
        fig = px.line(long, x="date", y="value", color="series")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend_title_text=None, yaxis_tickprefix="$")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Price-based. Total return including dividends is in the metrics above.")
    with right:
        st.subheader("Sectors")
        st.bar_chart(data["sectors"], horizontal=True)

    st.subheader("Purchase lots")
    st.caption("Stored exactly as entered; prices are looked up on the purchase date and split-adjusted.")
    st.dataframe([{
        "id": hid, "ticker": r.ticker, "entered date": r.requested_date, "traded": r.trade_date,
        "price paid": round(r.price_paid, 2), "splits since": f"x{r.split_factor:g}",
        "shares bought": round(r.shares_bought, 4), "shares now": round(r.shares_now, 4),
        "cost": round(r.cost_basis, 2), "note": r.note or "",
    } for hid, r in data["lots"]], hide_index=True, use_container_width=True)

    with st.expander("Remove a lot"):
        options = {hid: f"#{hid} {r.ticker} bought {r.requested_date}" for hid, r in data["lots"]}
        target = st.selectbox("Lot", list(options), format_func=options.get)
        if st.button("Remove lot", type="secondary"):
            db.delete_holding(uid, target)
            load_portfolio.clear()
            flash(f"Removed {options[target]}.")
            st.rerun()
else:
    st.info("No holdings yet. Add one below.")

st.subheader("Add a holding")
st.caption("You're the one making this change here, so no agent approval is needed. "
           "The agent's add_holding tool asks first.")
with st.form("add_holding", clear_on_submit=True):
    c1, c2, c3, c4 = st.columns(4)
    ticker = c1.text_input("Ticker").strip().upper()
    pdate = c2.date_input("Purchase date", value=date(2024, 1, 2), max_value=date.today())
    mode = c3.radio("Enter as", ["Shares", "Dollars"], horizontal=True)
    qty = c4.number_input("Quantity", min_value=0.0, step=1.0)
    if st.form_submit_button("Add holding", type="primary"):
        try:
            kwargs = {"shares": qty} if mode == "Shares" else {"amount": qty}
            r = resolve_lot(Lot(ticker, pdate, **kwargs))  # validates ticker, date and quantity first
            db.add_holding(uid, r.ticker, pdate, **kwargs)
            load_portfolio.clear()
            flash(f"Added {r.ticker}: {r.shares_now:,.4f} shares, cost basis ${r.cost_basis:,.2f}"
                  + (f". {r.note}" if r.note else ""))
            st.rerun()
        except Exception as e:
            st.error(str(e))