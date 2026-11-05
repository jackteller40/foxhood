"""Run from the repo root:  python -m tests.smoke_mcp
Connects to our MCP server exactly the way the agent will (langchain-mcp-adapters, stdio)."""
from __future__ import annotations

import time

from agent.mcp_client import get_mcp_client
from core.async_utils import run_sync


async def main():
    t0 = time.time()
    client = get_mcp_client()

    print("=== tools discovered over MCP ===")
    tools = await client.get_tools()
    for t in tools:
        print(f"- {t.name}\n    desc: {t.description[:100]}...\n    args: {t.args}")
    by_name = {t.name: t for t in tools}

    print("\n=== call: get_macro_snapshot ===")
    print(str(await by_name["get_macro_snapshot"].ainvoke({}))[:800])

    print("\n=== call: get_series(DGS10, days=30) ===")
    print(str(await by_name["get_series"].ainvoke({"series_id": "DGS10", "days": 30}))[:600])

    print("\n=== call: get_series with a series NOT in the catalog (should be refused) ===")
    print(await by_name["get_series"].ainvoke({"series_id": "GOLDAMGBD228NLBM"}))

    print("\n=== call: get_upcoming_releases(days=14) ===")
    print(str(await by_name["get_upcoming_releases"].ainvoke({"days": 14}))[:1200])

    print("\n=== resources ===")
    for blob in await client.get_resources("macro"):
        print(f"- {blob.metadata.get('uri')}:\n{blob.as_string()[:250]}...\n")

    print(f"Finished in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    run_sync(main())
    