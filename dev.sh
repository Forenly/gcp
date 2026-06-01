#!/usr/bin/env bash
#
# Dev mode — hot-reload the Lawn Advisor locally, served at https://lawn-dev.forenly.ai
# Edit any file under agent/src/ (incl. static/index.html) and just refresh the browser.
#
# Prod (lawn.forenly.ai) stays on Cloud Run, untouched. When happy: ./deploy.sh
#
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=project-8925a333-2bd2-47ba-af2
sm(){ gcloud secrets versions access latest --secret="$1" --project "$PROJECT" 2>/dev/null; }

export GCP_PROJECT="$PROJECT"
export VERTEX_LOCATION=us-central1
export GEMINI_MODEL_NAME=gemini-2.5-flash
export MONGODB_DB=lawn_advisor
export MONGODB_URI="$(sm mongodb-uri)"
export MAPS_SERVER_KEY="$(sm maps-server-key)"
export MAPS_BROWSER_KEY="$(sm maps-browser-key)"

echo "🔥 Dev hot-reload → https://lawn-dev.forenly.ai  (localhost:8000)"
echo "   Edit agent/src/* and refresh the browser. Ctrl+C to stop."
exec ~/lawn-dev-venv/bin/uvicorn server:app \
  --reload --reload-dir agent/src \
  --host 127.0.0.1 --port 8000 \
  --app-dir agent/src
