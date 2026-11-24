"""uv run python -m jobs briefs | alerts"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from jobs.alerts import run_alerts
from jobs.morning_briefs import run_morning_briefs
from jobs.record import recorded

JOBS = {"briefs": run_morning_briefs, "alerts": run_alerts}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run a Foxhood scheduled job once.")
    parser.add_argument("job", choices=sorted(JOBS))
    name = parser.parse_args().job
    print(json.dumps(asyncio.run(recorded(name, JOBS[name])), indent=2))
