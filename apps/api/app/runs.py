"""Agent runs started from the API: one at a time per user, streamed to the browser as server-sent events.

The run itself is a background task that feeds events into a queue; the HTTP response only reads
from that queue. If the browser disconnects, the response stops but the run finishes anyway, so a
thread is never left half-saved and the answer is waiting when the user comes back.

Note: the one-run-per-user lock lives in this process. Production runs a single API instance (M7)."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from agent.tracing import EventSink

log = logging.getLogger(__name__)

PING_SECONDS = 15   # keeps proxies from closing a quiet stream while a slow tool runs

_active: dict[uuid.UUID, asyncio.Task] = {}


def is_busy(user_id: uuid.UUID) -> bool:
    task = _active.get(user_id)
    return task is not None and not task.done()


def start_run(user_id: uuid.UUID, job: Callable[[EventSink], Awaitable[object]]) -> StreamingResponse:
    """Start job(on_event) in the background and stream its events. 409 if this user already has a run."""
    if is_busy(user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a request running. Wait for it to finish.")
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def runner() -> None:
        try:
            await job(queue.put_nowait)
        except Exception as e:   # the agent already emitted an "error" event for its own failures
            log.exception("Agent run failed for user %s", user_id)
            queue.put_nowait({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            queue.put_nowait(None)   # end of stream
            _active.pop(user_id, None)

    _active[user_id] = asyncio.create_task(runner())   # registered before any await: no double-start race
    return StreamingResponse(_sse(queue), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def sse_message(event: dict) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, default=str)}\n\n"


def single_event_response(event: dict) -> StreamingResponse:
    """Same SSE shape for answers that need no run (e.g. a brief that's already saved)."""
    async def one() -> AsyncIterator[str]:
        yield sse_message(event)
    return StreamingResponse(one(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


async def _sse(queue: asyncio.Queue[dict | None]) -> AsyncIterator[str]:
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
        except TimeoutError:
            yield ": ping\n\n"
            continue
        if event is None:
            return
        yield sse_message(event)