# `agent/` — Gemini + MongoDB MCP

This is where the actual agent code lives. The agent is orchestrated by
Vertex AI Agent Builder; this directory holds:

- `src/seed_db.py` — one-shot script that loads the JSON in `../data/seed/`
  into a MongoDB Atlas cluster.
- `src/mcp_client.py` — thin client around the MongoDB MCP server (used both
  for testing tools locally and by the Cloud Run service).
- `src/server.py` — FastAPI service deployed to Cloud Run. Receives yard
  JSON, invokes the agent, returns the recommendation + plan.
- `src/prompts/` — system + retrieval + planning prompt templates.
- `tests/` — pytest cases that exercise the agent end-to-end against a
  small fixture DB.

> Code is intentionally not yet committed in detail — see ARCHITECTURE.md
> for the planned shape. First implementation lands once
> `data/seed/*.json` is populated (issue #12).

## Configuration

Required env vars (load from `.env` locally, from Cloud Run secrets in prod):

| Var                | Where it comes from                                      |
|--------------------|----------------------------------------------------------|
| `MONGODB_URI`      | Mongo Atlas connection string                            |
| `MONGODB_DB`       | usually `lawn_advisor`                                   |
| `GCP_PROJECT`      | `project-f3c4dc98-497f-4eee-b60` (see `docs/GCP_SETUP.md`) |
| `VERTEX_LOCATION`  | `us-central1`                                            |
| `AGENT_RESOURCE`   | the Agent Builder agent's resource name                  |

`.env.example` at repo root lists the same shape.

## Local dev

```bash
# from repo root
python -m venv .venv && source .venv/bin/activate
pip install -r agent/requirements.txt   # lands in next PR
python agent/src/seed_db.py             # one-shot
uvicorn agent.src.server:app --reload --port 8000
```

## Cloud Run

Build + deploy (lands when the service is ready):
```bash
gcloud run deploy lawn-advisor \
  --source=agent \
  --region=us-central1 \
  --allow-unauthenticated \
  --project=project-f3c4dc98-497f-4eee-b60
```
