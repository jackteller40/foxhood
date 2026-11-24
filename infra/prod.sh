#!/usr/bin/env bash
# Run an admin command against PRODUCTION with the production database AND encryption key.
# (Using your laptop's key on production data writes rows the live site can't read.)
#   bash infra/prod.sh invite friend@gmail.com
#   bash infra/prod.sh seed-demo demo@gmail.com --persona aggressive
#   bash infra/prod.sh list-invites
set -euo pipefail
[[ $# -gt 0 ]] || { sed -n '2,7p' "$0"; exit 1; }
cd "$(dirname "$0")/../apps/api"
DATABASE_URL="$(gcloud secrets versions access latest --secret=database-url)" \
FOXHOOD_DATA_KEYS="$(gcloud secrets versions access latest --secret=foxhood-data-keys)" \
  uv run python -m app.cli "$@"
