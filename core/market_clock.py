"""Which brief to show, using the NYSE calendar (weekends, holidays, half days).

Trading day, before close + 15 min  -> pre-market brief for today
Trading day, after close + 15 min   -> post-close recap for today
Non-trading day                     -> post-close recap for the last session"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import exchange_calendars as xcals
import pandas as pd

from datasources.market import ET

CLOSE_SETTLE = timedelta(minutes=15)  # let closing prices settle before the recap
_calendar = None


def _cal():
    global _calendar
    if _calendar is None:
        _calendar = xcals.get_calendar("XNYS")
    return _calendar


@dataclass(frozen=True)
class BriefSlot:
    session: str       # "premarket" | "close"
    brief_date: date   # the trading day the brief is about
    reason: str


def is_trading_day(d: date) -> bool:
    return bool(_cal().is_session(pd.Timestamp(d)))


def current_brief_slot(now: datetime | None = None) -> BriefSlot:
    now = (now or datetime.now(ET)).astimezone(ET)
    cal = _cal()
    today = pd.Timestamp(now.date())

    if cal.is_session(today):
        close_et = cal.session_close(today).tz_convert(ET)
        if now >= close_et + CLOSE_SETTLE:
            return BriefSlot("close", now.date(), f"after today's close ({close_et:%I:%M %p} ET)")
        return BriefSlot("premarket", now.date(), f"before today's close ({close_et:%I:%M %p} ET)")

    prev = cal.date_to_session(today, direction="previous")
    return BriefSlot("close", prev.date(), "market closed today; showing the last session's recap")