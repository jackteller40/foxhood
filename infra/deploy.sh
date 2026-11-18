#!/usr/bin/env bash
# Build both images with Cloud Build, run database migrations, then deploy the API and the site.
# Run from the repo root:  bash infra/deploy.sh      (later, GitHub Actions does the same on every push)
set -euo pipefail

PROJECT="$(gcloud config get-value project 2>/dev/null)"
REGION="us-east1"
REPO="$REGION-docker.pkg.dev/$PROJECT/foxhood"
TAG="$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- apps || echo -dirty)"
SITE_URL="https://foxhood.app"
echo "Deploying $TAG to $PROJECT"

echo "== Building images (takes a few minutes the first time) =="
gcloud builds submit apps/api --tag "$REPO/api:$TAG" --quiet
gcloud builds submit apps/web --tag "$REPO/web:$TAG" --quiet

API_SECRETS="ANTHROPIC_API_KEY=anthropic-api-key:latest,FRED_API_KEY=fred-api-key:latest,\
FINNHUB_API_KEY=finnhub-api-key:latest,TIINGO_API_KEY=tiingo-api-key:latest,RESEND_API_KEY=resend-api-key:latest,\
DATABASE_URL=database-url:latest,FOXHOOD_DATA_KEYS=foxhood-data-keys:latest,API_JWT_SECRET=api-jwt-secret:latest,\
JOBS_SECRET=jobs-secret:latest"

echo "== Migrating the database =="
gcloud run jobs deploy foxhood-migrate --image "$REPO/api:$TAG" --region "$REGION" --quiet \
  --service-account "foxhood-api@$PROJECT.iam.gserviceaccount.com" \
  --set-secrets "$API_SECRETS" --command alembic --args upgrade,head --max-retries 0 --task-timeout 300
gcloud run jobs execute foxhood-migrate --region "$REGION" --wait

echo "== Deploying the API =="
gcloud run deploy foxhood-api --image "$REPO/api:$TAG" --region "$REGION" --quiet \
  --service-account "foxhood-api@$PROJECT.iam.gserviceaccount.com" \
  --set-secrets "$API_SECRETS" --set-env-vars "^|^APP_URL=$SITE_URL|EMAIL_FROM=Foxhood <brief@foxhood.app>" \
  --allow-unauthenticated --memory 1Gi --cpu 1 --concurrency 20 \
  --min-instances 0 --max-instances 3 --timeout 900
API_URL="$(gcloud run services describe foxhood-api --region "$REGION" --format='value(status.url)')"

echo "== Deploying the site =="
gcloud run deploy foxhood-web --image "$REPO/web:$TAG" --region "$REGION" --quiet \
  --service-account "foxhood-web@$PROJECT.iam.gserviceaccount.com" \
  --set-secrets "AUTH_SECRET=auth-secret:latest,AUTH_GOOGLE_ID=auth-google-id:latest,\
AUTH_GOOGLE_SECRET=auth-google-secret:latest,API_JWT_SECRET=api-jwt-secret:latest" \
  --set-env-vars "API_URL=$API_URL,AUTH_TRUST_HOST=true" \
  --allow-unauthenticated --memory 512Mi --cpu 1 --concurrency 40 \
  --min-instances 0 --max-instances 3 --timeout 900

echo "== Health check =="
curl -fsS "$API_URL/health" && echo
echo "Site (until foxhood.app is connected): $(gcloud run services describe foxhood-web --region "$REGION" --format='value(status.url)')"
