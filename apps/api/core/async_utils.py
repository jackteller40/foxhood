"""Run async code (the MCP client) from sync code (Streamlit, scripts)."""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine


def run_sync(coro: Coroutine) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # normal case: no loop running in this thread

    # A loop is already running here; run the coroutine on a fresh loop in a worker thread.
    result: dict[str, Any] = {}

    def worker():
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as e:  # re-raised below in the caller's thread
            result["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    if "error" in result:
        raise result["error"]
    return result["value"]