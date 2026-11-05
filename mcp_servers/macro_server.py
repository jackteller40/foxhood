"""MCP server exposing FRED macro data. The agent starts it over stdio:
    python -m mcp_servers.macro_server

IMPORTANT: never print() in this file. With stdio transport, stdout carries the
MCP protocol; a stray print corrupts it. Log to stderr instead."""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

from datasources import macro

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[macro-mcp] %(message)s")
log = logging.getLogger("macro_mcp")

mcp = FastMCP("macro-data")


@mcp.tool()
def get_macro_snapshot() -> dict:
    """Latest reading and 1-month change for key US macro indicators: effective fed funds
    rate, 2y and 10y Treasury yields, 10y-2y spread, CPI (with YoY %), unemployment rate,
    high-yield credit spread, and VIX. Use this for rates/inflation/risk context."""
    log.info("tool get_macro_snapshot")
    try:
        snap = macro.get_macro_snapshot()
        if not snap:
            return {"error": "Macro snapshot came back empty (no series returned)."}
        return snap
    except Exception as e:
        log.exception("get_macro_snapshot failed")
        return {"error": str(e)}


@mcp.tool()
def get_series(series_id: str, days: int = 90) -> dict:
    """Recent observations (up to the last 30) for one macro series over the past `days` days.
    series_id must be in the catalog (resource macro://series-catalog), e.g. DGS10, CPIAUCSL."""
    sid = series_id.strip().upper()
    log.info("tool get_series series_id=%s days=%s", sid, days)
    if sid not in macro.KEY_SERIES:
        return {"error": f"Series '{sid}' is not in the catalog. Allowed: {sorted(macro.KEY_SERIES)}"}
    days = max(5, min(int(days), 730))
    try:
        s = macro.get_series(sid, start=date.today() - timedelta(days=days))
    except Exception as e:
        log.exception("get_series failed")
        return {"error": str(e)}
    return {
        "series_id": sid,
        "label": macro.KEY_SERIES[sid],
        "observations": [{"date": d.date().isoformat(), "value": float(v)} for d, v in s.tail(30).items()],
    }


@mcp.tool()
def get_upcoming_releases(days: int = 7) -> dict:
    """Scheduled dates for market-moving US economic releases (CPI, jobs report, GDP,
    PCE, PPI, retail sales, FOMC rate decisions) within the next `days` days."""
    log.info("tool get_upcoming_releases days=%s", days)
    try:
        days = max(1, min(int(days), 45))
        return {"days": days, "releases": macro.get_upcoming_releases(days)}
    except Exception as e:
        log.exception("get_upcoming_releases failed")
        return {"error": str(e)}


@mcp.resource("macro://series-catalog")
def series_catalog() -> str:
    """The macro series the agent may request, with labels."""
    return json.dumps(macro.KEY_SERIES, indent=2)


@mcp.resource("macro://snapshot")
def snapshot_resource() -> str:
    """Current macro snapshot as a JSON document."""
    return json.dumps(macro.get_macro_snapshot(), indent=2)


if __name__ == "__main__":
    log.info("starting macro-data MCP server (stdio)")
    mcp.run(transport="stdio")