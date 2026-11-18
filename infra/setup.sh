#!/usr/bin/env bash
# One-time Google Cloud setup for Foxhood: image registry, service accounts, and secrets.
# Run from the repo root:  bash infra/setup.sh
# Safe to re-run: existing pieces are skipped. Secret VALUES are never printed except the new data key,
# which is shown once so you can save it in your password manager.
set -euo pipefail

PROJECT="$(gcloud config get-value project 2>/dev/null)"
REGION="us-east1"
[[ -n "$PROJECT" ]] || { echo "No project set. Run: gcloud config set project YOUR_PROJECT_ID"; exit 1; }
[[ -f apps/api/.env && -f apps/web/.env.local ]] || { echo "Run this from the repo root (needs apps/api/.env and apps/web/.env.local)."; exit 1; }
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
echo "Project: $PROJECT ($NUMBER), region $REGION"

# ---- image registry ----
gcloud artifacts repositories describe foxhood --location="$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create foxhood --repository-format=docker --location="$REGION" \
    --description="Foxhood container images"

# Cloud Build runs as the Compute Engine default account in new projects; let it build and push images.
gcloud projects add-iam-policy-binding "$PROJECT" --condition=None --quiet \
  --member="serviceAccount:${NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder" >/dev/null

# ---- service accounts: each service only gets the secrets it needs ----
for sa in foxhood-api foxhood-web; do
  gcloud iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$sa" --display-name="$sa (Cloud Run)"
done

# ---- secrets ----
from_file() {  # value of KEY in an env file (strips surrounding quotes)
  local v; v="$(grep -E "^$2=" "$1" | tail -1 | cut -d= -f2- || true)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"; printf '%s' "$v"
}
put() {  # put NAME VALUE: create the secret, or skip if it already exists
  local name="$1" value="$2"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then echo "  $name: exists, kept"; return; fi
  [[ -n "$value" ]] || { echo "  $name: EMPTY, not created. Fix and re-run."; return; }
  printf '%s' "$value" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic >/dev/null
  echo "  $name: created"
}
grant() {  # grant SECRET SERVICE_ACCOUNT
  gcloud secrets add-iam-policy-binding "$1" --quiet --role=roles/secretmanager.secretAccessor \
    --member="serviceAccount:$2@$PROJECT.iam.gserviceaccount.com" >/dev/null
}

echo "Secrets copied from your .env files:"
put anthropic-api-key "$(from_file apps/api/.env ANTHROPIC_API_KEY)"
put fred-api-key "$(from_file apps/api/.env FRED_API_KEY)"
put finnhub-api-key "$(from_file apps/api/.env FINNHUB_API_KEY)"
put tiingo-api-key "$(from_file apps/api/.env TIINGO_API_KEY)"
put resend-api-key "$(from_file apps/api/.env RESEND_API_KEY)"
put auth-google-id "$(from_file apps/web/.env.local AUTH_GOOGLE_ID)"
put auth-google-secret "$(from_file apps/web/.env.local AUTH_GOOGLE_SECRET)"

echo "Secrets generated fresh for production (different from your laptop's):"
put api-jwt-secret "$(openssl rand -hex 32)"
put auth-secret "$(openssl rand -base64 33)"
put jobs-secret "$(openssl rand -hex 32)"

if ! gcloud secrets describe database-url >/dev/null 2>&1; then
  read -rsp "Paste the Neon connection string (direct, not pooled; input hidden): " NEON_URL; echo
  put database-url "$NEON_URL"; unset NEON_URL
else
  echo "  database-url: exists, kept"
fi

if ! gcloud secrets describe foxhood-data-keys >/dev/null 2>&1; then
  DATA_KEY="v1:$(openssl rand -base64 32)"
  put foxhood-data-keys "$DATA_KEY"
  echo
  echo "================ SAVE THIS IN YOUR PASSWORD MANAGER NOW ================"
  echo "Production encryption key (FOXHOOD_DATA_KEYS). Lose it and every user's data is unreadable:"
  echo "$DATA_KEY"
  echo "========================================================================="
  echo "(Then clear the terminal: Cmd+K.)"
  unset DATA_KEY
else
  echo "  foxhood-data-keys: exists, kept"
fi

for s in anthropic-api-key fred-api-key finnhub-api-key tiingo-api-key resend-api-key database-url \
         foxhood-data-keys api-jwt-secret jobs-secret; do grant "$s" foxhood-api; done
for s in auth-google-id auth-google-secret auth-secret api-jwt-secret; do grant "$s" foxhood-web; done
echo "Done. Next: bash infra/deploy.sh"
