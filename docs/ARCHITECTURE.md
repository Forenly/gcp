# Architecture

## Components

```
        ┌─────────────────────────────────────────────────────┐
        │                  USER (web UI)                       │
        │       enters a yard description (form / JSON)       │
        └────────────────────┬────────────────────────────────┘
                             │  HTTP
                             ▼
        ┌─────────────────────────────────────────────────────┐
        │              Cloud Run service                       │
        │              (FastAPI / Express)                     │
        │   • receives yard input                              │
        │   • calls the Agent Builder agent                    │
        │   • returns plan JSON to the UI                      │
        └────────────────────┬────────────────────────────────┘
                             │  Vertex AI Agent Builder
                             ▼
        ┌─────────────────────────────────────────────────────┐
        │            Gemini Agent (Agent Builder)              │
        │                                                      │
        │   Reasoning steps:                                   │
        │     1. shortlist candidate mowers                    │
        │     2. recall similar past yards / plans             │
        │     3. score + pick                                  │
        │     4. draft a deployment plan                       │
        │     5. persist as new plan record                    │
        └────────────────────┬────────────────────────────────┘
                             │  MongoDB MCP server
                             ▼
        ┌─────────────────────────────────────────────────────┐
        │                MongoDB Atlas (free tier)             │
        │                                                      │
        │   Collections:                                       │
        │     • mower_models                                   │
        │     • yards                                          │
        │     • deployment_plans                               │
        └─────────────────────────────────────────────────────┘
```

## Data flow

1. **Inbound** — User fills a small form (or hits an API with JSON):
   yard area, slope, obstacle list, boundary type, charging access.

2. **Retrieval (via MCP)** — Agent calls MongoDB MCP tools:
   - `find_mower_models(criteria)` → narrows the catalog to candidates that
     match yard size, slope, obstacle handling and boundary type.
   - `find_similar_yards(features)` → pulls archetypal yards close to the
     new one in feature space.
   - `find_past_plans(model_ids, yard_features)` → past deployments and how
     they were configured.

3. **Reasoning (Gemini)** — Agent ranks candidates, picks one, and drafts a
   deployment plan: boundary placement, dock location, first-mow zones,
   schedule.

4. **Persistence (via MCP)** — Agent calls `insert_deployment_plan(plan)` to
   write the new plan back. That record becomes a source for future
   retrievals.

5. **Outbound** — Cloud Run returns:
   ```json
   {
     "recommended_mower": { ... },
     "alternatives": [ ... ],
     "deployment_plan": { ... },
     "trace_id": "<plan_id>"
   }
   ```

## Stack

| Layer          | Choice                                    | Why                                    |
|----------------|-------------------------------------------|----------------------------------------|
| Model          | **Gemini 2.5** via Vertex AI              | Required by the Rapid Agent Hackathon  |
| Orchestration  | **Vertex AI Agent Builder**               | Required by the Rapid Agent Hackathon  |
| Data           | **MongoDB Atlas (M0 free)**               | Partner track is **MongoDB MCP**       |
| Tool surface   | **MongoDB MCP server**                    | The Agent Builder ↔ DB bridge          |
| Hosting        | **Cloud Run** (single container)          | Submission requirement: live demo URL  |
| Repo           | **Forenly/gcp** (public, Apache-2.0)      | Submission requirement                 |

## Deferred to v2

- Authentication / multi-tenant (single demo user is fine for v1)
- Image-based yard input (text + structured input for v1; vision is later)
- Feedback loop / re-rank from actual install outcomes
- Mower pricing localisation
