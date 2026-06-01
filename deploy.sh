#!/usr/bin/env bash
#
# One-shot deploy of the Lawn-Mower Advisor to Cloud Run.
#
# Prereqs (already true on the Forenly GCP project):
#   - run / aiplatform / cloudbuild / artifactregistry APIs enabled
#   - a Secret Manager secret named `mongodb-uri` holding the Atlas SRV string:
#       printf '%s' 'mongodb+srv://USER:PASS@CLUSTER.mongodb.net/?retryWrites=true&w=majority' \
#         | gcloud secrets create mongodb-uri --data-file=- --project "$PROJECT"
#   - the Cloud Run runtime SA granted roles/secretmanager.secretAccessor on it
#
# Usage: ./deploy.sh
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-8925a333-2bd2-47ba-af2}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-lawn-advisor}"

echo "Deploying '$SERVICE' to Cloud Run (project=$PROJECT region=$REGION)…"

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --set-env-vars "GCP_PROJECT=${PROJECT},VERTEX_LOCATION=${REGION},MONGODB_DB=lawn_advisor" \
  --set-secrets "MONGODB_URI=mongodb-uri:latest"

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
echo
echo "✅ Live: $URL"
echo "   Health:    curl $URL/"
echo "   Recommend: curl -X POST $URL/recommend -H 'Content-Type: application/json' -d '{\"area_sqm\":1200,\"slope_pct\":15,\"obstacles\":[\"pond\"],\"boundary_type\":\"fenced\",\"charging_access\":\"patio-outlet\",\"terrain\":\"complex-obstacles\"}'"
