"""Portfolio views, value history, CSV import, and upcoming earnings for the signed-in user."""
from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, HTTPException, status

from app.deps import RepoDep
from app.schemas import ImportCommitIn, ImportCommitOut, ImportPreviewIn, ImportPreviewOut
from datasources import market
from portfolio import service

router = APIRouter()


@router.get("/portfolio")
async def portfolio(repo: RepoDep) -> dict:
    """Positions with live values, totals vs SPY, sector mix. Empty portfolio -> summary null."""
    return await service.portfolio_view(repo.user_id, await repo.list_holdings())


@router.get("/portfolio/history")
async def portfolio_history(repo: RepoDep, range: str = "1y") -> dict:
    """Daily value of the portfolio vs the same dollars in SPY vs money invested (for the chart)."""
    return await service.history_view(repo.user_id, await repo.list_holdings(), range)


@router.get("/earnings/upcoming")
async def upcoming_earnings(repo: RepoDep, days: int = 14) -> dict:
    tickers = sorted({h.ticker for h in await repo.list_holdings()} | {w.ticker for w in await repo.list_watchlist()})
    rows = await asyncio.to_thread(market.get_earnings_calendar, tickers, max(1, min(days, 30))) if tickers else []
    return {"tickers": tickers, "earnings": rows}


@router.post("/holdings/import/preview", response_model=ImportPreviewOut)
async def import_preview(body: ImportPreviewIn) -> ImportPreviewOut:
    """Parse and price each CSV row; nothing is saved. The page shows this, then calls /commit."""
    rows = await service.check_rows(service.parse_csv(body.csv))
    ok = sum(r["status"] == "ok" for r in rows)
    return ImportPreviewOut(rows=rows, ok=ok, errors=len(rows) - ok)


@router.post("/holdings/import/commit", response_model=ImportCommitOut, status_code=status.HTTP_201_CREATED)
async def import_commit(body: ImportCommitIn, repo: RepoDep) -> ImportCommitOut:
    """Re-checks every row (never trusts the preview), then saves all of them or none."""
    rows = [{"row": i + 1, "ticker": r.ticker.strip().upper(), "purchase_date": r.purchase_date,
             "shares": r.shares, "amount": r.amount} for i, r in enumerate(body.rows)]
    checked = await service.check_rows(rows)
    bad = [r for r in checked if r["status"] != "ok"]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"message": "Some rows failed; nothing was saved.", "rows": bad})
    for r in checked:
        await repo.add_holding(r["ticker"], date.fromisoformat(str(r["purchase_date"])),
                               shares=r["shares"], amount=r["amount"], source="csv")
    return ImportCommitOut(created=len(checked))