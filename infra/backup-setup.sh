#!/usr/bin/env bash
# One-time: a private bucket for nightly database backups (deleted after 30 days, as the privacy page says)
# and a backup account that GitHub Actions can use. Run from the repo root:  bash infra/backup-setup.sh
set -euo pipefail

REPO_SLUG="jackteller40/foxhood"
PROJECT="$(gcloud config get-value project 2>/dev/null)"
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
REGION="us-east1"
BUCKET="gs://$PROJECT-backups"
SA="foxhood-backup@$PROJECT.iam.gserviceaccount.com"

if ! gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1; then
  # No public access, one permission model, no "soft delete" grace copies (so 30 days really means 30 days).
  gcloud storage buckets create "$BUCKET" --location "$REGION" --uniform-bucket-level-access \
    --public-access-prevention --soft-delete-duration=0
fi
POLICY="$(mktemp)"
echo '{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]}' > "$POLICY"
gcloud storage buckets update "$BUCKET" --lifecycle-file="$POLICY" >/dev/null
rm -f "$POLICY"

gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 ||
  gcloud iam service-accounts create foxhood-backup --display-name="Nightly database backup"
# It can add files to the bucket (not read, change or delete them) and read the database address. Nothing else.
gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="serviceAccount:$SA" \
  --role=roles/storage.objectCreator >/dev/null
gcloud secrets add-iam-policy-binding database-url --quiet --member="serviceAccount:$SA" \
  --role=roles/secretmanager.secretAccessor >/dev/null
# Same GitHub trust as deploys (this repo, main branch only).
gcloud iam service-accounts add-iam-policy-binding "$SA" --quiet --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO_SLUG" >/dev/null

echo
echo "Done. Add two more repository VARIABLES on GitHub:"
echo "  GCP_BACKUP_SA      = $SA"
echo "  GCP_BACKUP_BUCKET  = $BUCKET"
