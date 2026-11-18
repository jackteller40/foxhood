"""uv run python -m jobs briefs | alerts"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from jobs.alerts import run_alerts
from jobs.morning_briefs import run_morning_briefs

JOBS = {"briefs": run_morning_briefs, "alerts": run_alerts}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run a Foxhood scheduled job once.")
    parser.add_argument("job", choices=sorted(JOBS))
    print(json.dumps(asyncio.run(JOBS[parser.parse_args().job]()), indent=2))
