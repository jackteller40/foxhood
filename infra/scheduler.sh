#!/usr/bin/env bash
# Create (or update) the two Cloud Scheduler jobs that call the API's /jobs endpoints.
# Times are US Eastern, daylight saving handled by Scheduler. Run from the repo root:  bash infra/scheduler.sh
set -euo pipefail

REGION="us-east1"
TZ_NAME="America/New_York"
API_URL="$(gcloud run services describe foxhood-api --region "$REGION" --format='value(status.url)')"
JOB_KEY="$(gcloud secrets versions access latest --secret=jobs-secret)"

job() {  # job NAME SCHEDULE PATH DEADLINE DESCRIPTION
  local verb=create
  gcloud scheduler jobs describe "$1" --location "$REGION" >/dev/null 2>&1 && verb=update
  local headers_flag="--headers"; [[ $verb == update ]] && headers_flag="--update-headers"
  gcloud scheduler jobs "$verb" http "$1" --location "$REGION" --quiet \
    --schedule "$2" --time-zone "$TZ_NAME" --uri "$API_URL$3" --http-method POST \
    "$headers_flag" "X-Job-Key=$JOB_KEY,Content-Type=application/json" --message-body '{}' \
    --attempt-deadline "$4" --max-retry-attempts 1 --min-backoff 60s --description "$5" >/dev/null
  echo "  $1: ${verb}d ($2 $TZ_NAME)"
}

echo "Scheduler jobs for $API_URL"
# Weekdays 8:30 a.m. The job itself skips market holidays and anyone with a brief already.
job foxhood-morning-briefs "30 8 * * 1-5" /jobs/briefs 1800s "Write every user's pre-market brief"
# Weekdays every 30 minutes, 9:00 a.m. to 4:30 p.m. (covers the whole session; no AI, so it's free).
job foxhood-alerts "*/30 9-16 * * 1-5" /jobs/alerts 600s "Check big moves, earnings tomorrow and position limits"
unset JOB_KEY
echo "Done. Try one now:  gcloud scheduler jobs run foxhood-alerts --location $REGION"
