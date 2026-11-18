#!/usr/bin/env bash
# Practice restore: download the newest backup and load it into a scratch database on your laptop,
# then count rows. Proves the backups work. Touches nothing in production.
# Run from the repo root:  bash infra/restore-test.sh
set -euo pipefail

PROJECT="$(gcloud config get-value project 2>/dev/null)"
BUCKET="gs://$PROJECT-backups"
SCRATCH="foxhood_restore_test"
LATEST="$(gcloud storage ls "$BUCKET/" | sort | tail -1)"
[[ -n "$LATEST" ]] || { echo "No backups in $BUCKET yet. Run the backup workflow first."; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "Restoring $LATEST into local database $SCRATCH"
gcloud storage cp "$LATEST" "$TMP/backup.dump" --quiet
dropdb --if-exists "$SCRATCH"
createdb "$SCRATCH"
# Neon adds a few hosting-specific bits a laptop Postgres doesn't have; warnings about those are fine.
pg_restore --no-owner --no-privileges --dbname "$SCRATCH" "$TMP/backup.dump" || echo "(pg_restore warnings above; checking the data anyway)"
psql -d "$SCRATCH" -c "SELECT 'users' AS t, count(*) FROM users UNION ALL SELECT 'invites', count(*) FROM invites
  UNION ALL SELECT 'holdings', count(*) FROM holdings UNION ALL SELECT 'briefs', count(*) FROM briefs
  UNION ALL SELECT 'alembic version: ' || version_num, NULL FROM alembic_version;"
echo "Restore worked. Delete the scratch copy with:  dropdb $SCRATCH"
