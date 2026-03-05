#!/bin/bash
# Build & Deploy HelloCity (FastAPI + Vite React) to Google App Engine
#
# Prerequisites:
#   1) gcloud SDK installed: https://cloud.google.com/sdk/docs/install
#   2) gcloud auth login
#   3) gcloud config set project YOUR_PROJECT_ID
#   4) Python + Node/npm installed locally
#
# Usage:
#   chmod +x ./deploy_gcp.sh
#   ./deploy_gcp.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "══════════════════════════════════════════════════════════"
echo "  HelloCity Onboarding — Build & Deploy (App Engine)"
echo "══════════════════════════════════════════════════════════"

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [ -z "$PROJECT_ID" ]; then
  echo "ERROR: No gcloud project set. Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

# OPENAI_API_KEY: optional. If set, passed to App Engine; if not, app uses Secret Manager (openai-api-key) in production.
APP_URL="https://${PROJECT_ID}.appspot.com"

echo ""
echo "▸ Step 1/2: Building frontend (Vite)..."
cd frontend

# Use empty base URL so API calls are same-origin (avoids CORS / wrong host in prod)
cat > .env.production <<EOF
VITE_API_BASE_URL=
EOF

npm install
npm run build
cd ..
echo "  Frontend built to frontend/dist"

echo ""
echo "▸ Step 2/2: Deploying to App Engine..."
if [ -n "$OPENAI_API_KEY" ]; then
  gcloud app deploy app.yaml --quiet --set-env-vars="OPENAI_API_KEY=${OPENAI_API_KEY}"
else
  echo "  (OPENAI_API_KEY not set; app will use Secret Manager 'openai-api-key' in production)"
  gcloud app deploy app.yaml --quiet
fi

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  App should be live at:"
echo "  ${APP_URL}"
echo "══════════════════════════════════════════════════════════"

