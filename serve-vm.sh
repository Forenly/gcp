#!/usr/bin/env bash
#
# Production serve of the Lawn Advisor ON THE FORENLY VM (not Cloud Run).
# Pulls secrets from Secret Manager at boot, then runs uvicorn on a fixed
# local port. The CF tunnel (`forenly`) routes lawn.forenly.ai → this port.
#
# Driven by systemd unit lawn-advisor.service. Dev hot-reload is still ./dev.sh.
#
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=project-8925a333-2bd2-47ba-af2
sm(){ gcloud secrets versions access latest --secret="$1" --project "$PROJECT"; }

export GCP_PROJECT="$PROJECT"
export VERTEX_LOCATION=us-central1
export GEMINI_MODEL_NAME=gemini-2.5-flash
export MONGODB_DB=lawn_advisor
export MONGODB_URI="$(sm mongodb-uri)"
export MAPS_SERVER_KEY="$(sm maps-server-key)"
export MAPS_BROWSER_KEY="$(sm maps-browser-key)"

PORT="${PORT:-8200}"
exec /home/macb/lawn-dev-venv/bin/uvicorn server:app \
  --host 127.0.0.1 --port "$PORT" \
  --app-dir agent/src
