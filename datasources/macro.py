"""Macro data from FRED (St. Louis Fed): series observations + economic release calendar."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests

from core.config import settings
from datasources.cache import cached

FRED_BASE = "https://api.stlouisfed.org/fred"

KEY_SERIES = {
    "DFF": "Fed funds rate (effective)",
    "DGS2": "2-year Treasury yield",
    "DGS10": "10-year Treasury yield",
    "T10Y2Y": "10y minus 2y spread",
    "CPIAUCSL": "CPI (index level)",
    "UNRATE": "Unemployment rate",
    "BAMLH0A0HYM2": "High-yield credit spread",
    "VIXCLS": "VIX",
}

# Substring of FRED's release_name (lowercase) -> short label for the brief
MAJOR_RELEASES = {
    "consumer price index": "CPI",
    "employment situation": "Jobs report",
    "gross domestic product": "GDP",
    "personal income and outlays": "PCE / personal income",
    "producer price index": "PPI",
    "advance monthly sales for retail": "Retail sales",
}
FOMC_DECISION_DATES = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
]

def _fred_get(path: str, params: dict) -> dict:
    if not settings.fred_api_key:
        raise RuntimeError("FRED_API_KEY missing from .env")
    resp = requests.get(
        f"{FRED_BASE}/{path}",
        params={**params, "api_key": settings.fred_api_key, "file_type": "json"},
        timeout=15,
    )
    if resp.status_code != 200:
        # Don't use raise_for_status(): its message includes the URL, which contains your key.
        try:
            msg = resp.json().get("error_message", resp.text)
        except ValueError:
            msg = resp.text
        raise RuntimeError(f"FRED error {resp.status_code} on {path}: {msg}")
    return resp.json()


@cached(ttl_seconds=6 * 3600)
def get_series(series_id: str, start: date | str | None = None) -> pd.Series:
    if start is None:
        start = date.today() - timedelta(days=400)
    data = _fred_get("series/observations", {"series_id": series_id, "observation_start": str(start)})
    obs = data.get("observations", [])
    s = pd.Series({pd.Timestamp(o["date"]): o["value"] for o in obs}, dtype="object")
    s = pd.to_numeric(s, errors="coerce").dropna()  # FRED uses "." for missing days
    s.name = series_id
    return s


def get_macro_snapshot() -> dict:
    """Latest value + 1-month change for each key series (CPI also gets YoY %)."""
    snapshot: dict[str, dict] = {}
    for sid, label in KEY_SERIES.items():
        try:
            s = get_series(sid)
        except Exception as e:
            snapshot[sid] = {"label": label, "error": str(e)}
            continue
        if s.empty:
            snapshot[sid] = {"label": label, "error": "no data"}
            continue

        latest_date = s.index[-1]
        latest = float(s.iloc[-1])
        month_ago = s.asof(latest_date - pd.Timedelta(days=30))
        entry = {
            "label": label,
            "value": round(latest, 3),
            "date": latest_date.date().isoformat(),
            "change_1m": None if pd.isna(month_ago) else round(latest - float(month_ago), 3),
        }
        if sid == "CPIAUCSL":
            year_ago = s.asof(latest_date - pd.Timedelta(days=365))
            entry["yoy_pct"] = None if pd.isna(year_ago) else round((latest / float(year_ago) - 1) * 100, 2)
        snapshot[sid] = entry
    return snapshot


@cached(ttl_seconds=6 * 3600)
def get_upcoming_releases(days: int = 7) -> list[dict]:
    """Scheduled dates for market-moving US releases in the next `days` days."""
    start = date.today()
    data = _fred_get("releases/dates", {
        "realtime_start": start.isoformat(),
        "realtime_end": (start + timedelta(days=days)).isoformat(),
        "include_release_dates_with_no_data": "true",
        "sort_order": "asc",
        "limit": 1000,
    })
    out, seen = [], set()
    for r in data.get("release_dates", []):
        name = r.get("release_name", "")
        label = next((v for k, v in MAJOR_RELEASES.items() if k in name.lower()), None)
        if not label or (r["date"], label) in seen:
            continue
        seen.add((r["date"], label))
        out.append({"date": r["date"], "event": label, "release_name": name})

    end = start + timedelta(days=days)
    for d in FOMC_DECISION_DATES:
        if start <= d <= end:
            out.append({"date": d.isoformat(), "event": "FOMC rate decision",
                        "release_name": "FOMC statement 2:00 pm ET, press conference 2:30 pm ET"})
    return sorted(out, key=lambda x: x["date"])