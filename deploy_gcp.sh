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

if [ -z "$OPENAI_API_KEY" ]; then
  echo "ERROR: OPENAI_API_KEY is not set in your shell."
  echo "Export it first, e.g.:"
  echo "  export OPENAI_API_KEY=\"sk-your-real-key\""
  exit 1
fi

APP_URL="https://${PROJECT_ID}.appspot.com"

echo ""
echo "▸ Step 1/2: Building frontend (Vite)..."
cd frontend

# Point frontend at the App Engine URL so API calls go to the same origin
cat > .env.production <<EOF
VITE_API_BASE_URL=${APP_URL}
EOF

npm install
npm run build
cd ..
echo "  Frontend built to frontend/dist"

echo ""
echo "▸ Step 2/2: Deploying to App Engine..."
gcloud app deploy app.yaml --quiet \
  --set-env-vars="OPENAI_API_KEY=${OPENAI_API_KEY}"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  App should be live at:"
echo "  ${APP_URL}"
echo "══════════════════════════════════════════════════════════"

