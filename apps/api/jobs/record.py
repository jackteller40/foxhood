"""Write each scheduled run to the job_runs table, so the admin page can show when it last worked."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from db.models import JobRun, utcnow
from db.session import SessionLocal

log = logging.getLogger("foxhood.jobs")


async def recorded(job: str, run: Callable[[], Awaitable[dict]]) -> dict:
    async with SessionLocal() as s:
        row = JobRun(job=job)
        s.add(row)
        await s.commit()
        run_id = row.id
    ok, summary = False, {}
    try:
        summary = await run()
        ok = not summary.get("outcomes", {}).get("failed")
        return summary
    except Exception as e:
        summary = {"error": type(e).__name__}
        log.exception("Job %s crashed", job)
        raise
    finally:
        async with SessionLocal() as s:
            row = await s.get(JobRun, run_id)
            row.finished_at, row.ok, row.summary = utcnow(), ok, summary
            await s.commit()
