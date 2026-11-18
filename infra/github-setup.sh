#!/usr/bin/env bash
# One-time: let GitHub Actions deploy Foxhood, with no stored keys (Workload Identity Federation).
# Only pushes to main in jackteller40/foxhood can use it, and the deploy account can only push images
# and update the Foxhood services. Run from the repo root:  bash infra/github-setup.sh
set -euo pipefail

REPO_SLUG="jackteller40/foxhood"
PROJECT="$(gcloud config get-value project 2>/dev/null)"
REGION="us-east1"
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
DEPLOYER="foxhood-deployer@$PROJECT.iam.gserviceaccount.com"

gcloud iam service-accounts describe "$DEPLOYER" >/dev/null 2>&1 ||
  gcloud iam service-accounts create foxhood-deployer --display-name="GitHub Actions deployer"

# What the deployer may do: manage Cloud Run, push images, and run services as the two app accounts.
gcloud projects add-iam-policy-binding "$PROJECT" --condition=None --quiet \
  --member="serviceAccount:$DEPLOYER" --role=roles/run.admin >/dev/null
gcloud artifacts repositories add-iam-policy-binding foxhood --location="$REGION" --quiet \
  --member="serviceAccount:$DEPLOYER" --role=roles/artifactregistry.writer >/dev/null
for sa in foxhood-api foxhood-web; do
  gcloud iam service-accounts add-iam-policy-binding "$sa@$PROJECT.iam.gserviceaccount.com" --quiet \
    --member="serviceAccount:$DEPLOYER" --role=roles/iam.serviceAccountUser >/dev/null
done

# Trust GitHub's identity tokens, but only from this repo's main branch.
gcloud iam workload-identity-pools describe github --location=global >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe github --location=global --workload-identity-pool=github >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc github --location=global --workload-identity-pool=github \
    --display-name="GitHub" --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='$REPO_SLUG' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" --quiet --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO_SLUG" >/dev/null

# Keep image storage inside the free tier: keep the 5 newest images of each app, delete the rest after 7 days.
POLICY="$(mktemp)"
cat > "$POLICY" <<'JSON'
[{"name": "keep-recent", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 5}},
 {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"olderThan": "7d"}}]
JSON
gcloud artifacts repositories set-cleanup-policies foxhood --location="$REGION" --policy="$POLICY" --no-dry-run --quiet >/dev/null
rm -f "$POLICY"

PROVIDER="projects/$NUMBER/locations/global/workloadIdentityPools/github/providers/github"
echo
echo "Done. Add these three repository VARIABLES on GitHub (Settings > Secrets and variables > Actions > Variables):"
echo "  GCP_PROJECT       = $PROJECT"
echo "  GCP_WIF_PROVIDER  = $PROVIDER"
echo "  GCP_DEPLOY_SA     = $DEPLOYER"
if command -v gh >/dev/null 2>&1; then
  echo "Or let the GitHub CLI do it:"
  echo "  gh variable set GCP_PROJECT -R $REPO_SLUG -b '$PROJECT'"
  echo "  gh variable set GCP_WIF_PROVIDER -R $REPO_SLUG -b '$PROVIDER'"
  echo "  gh variable set GCP_DEPLOY_SA -R $REPO_SLUG -b '$DEPLOYER'"
fi
