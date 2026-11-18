"""Scheduled work: the morning briefs and the alert checks. Each job is safe to run more than once
(already-written briefs and already-raised alerts are skipped), so a retried or doubled schedule is harmless.

Locally:   uv run python -m jobs briefs | alerts
Deployed:  Cloud Scheduler calls POST /jobs/<name> with the X-Job-Key header (app/routes/jobs.py)."""
