"""Macro series from FRED (St. Louis Fed)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests

from core.config import settings
from datasources.cache import cached

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

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

@cached(ttl_seconds=6 * 3600)
def get_series(series_id: str, start: date | str | None = None) -> pd.Series:
    if not settings.fred_api_key:
        raise RuntimeError("FRED_API_KEY missing from .env")
    if start is None:
        start = date.today() - timedelta(days=400)
        
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "observation_start": str(start),
    }
    resp = requests.get(FRED_URL, params=params, timeout=15)
    if resp.status_code != 200:
        try:
            msg = resp.json().get("error_message", resp.text)
        except ValueError:
            msg = resp.text
        raise RuntimeError(f"FRED error {resp.status_code} for {series_id}: {msg}")
    
    obs = resp.json().get("observations", [])
    s = pd.Series({pd.Timestamp(o["date"]): o["value"] for o in obs}, dtype="object")
    s = pd.to_numeric(s, errors="coerce").dropna()
    s.name = series_id
    return s

def get_macro_snapshot() -> dict:
    """Latest value + 1 month change for each key series (CPI also gets YoY %)"""
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