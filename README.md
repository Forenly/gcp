# gcp — Lawn Mower Deployment Advisor (Google Cloud + MongoDB)

> [!IMPORTANT]
> ### 🏆 GRAND PRIZE POOL: $60,000 USD ($10,000 per partner bucket!)
> **Partners:** Arize, Elastic, Fivetran, GitLab, MongoDB. Let's build the most rapid AI agent integrations on Google Cloud and claim the $60,000 bounty! ☁️⚡


[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)

> Submission for the **Google Cloud Rapid Agent Hackathon** — "Building Agents for Real-World Challenges". Partner track: **MongoDB MCP**.

## Community

Building this in the open — join the team chat on Discord: https://discord.gg/RTBbx3DjqC

## The problem

Picking the right robotic lawn mower for a specific yard — and getting it set up
to actually work there — is mostly trial and error today. Buyers and installers
juggle yard size, slope, obstacle layout, boundary type, charging access and
model-by-model spec sheets, then guess at install steps. Most of that knowledge
is locked in product PDFs, forum threads and people's heads.

## What we're building

An agent that takes a description of a target yard and returns:

1. A short list of **suitable mower models** from a curated registry, with the
   reasons each one fits (yard area, slope tolerance, obstacle handling,
   boundary technology, charging needs).
2. A **deployment plan** for the chosen model — boundary placement, charging
   dock location, first-mow zones, expected schedule.
3. A persistent **record of the recommendation** written back to the registry so
   later jobs can learn from past deployments.

The registry of mower models, yards, and past deployment plans lives in
**MongoDB** and is exposed to the agent through the **MongoDB MCP server**.

## How it's built

- **Model:** Gemini (Google Cloud)
- **Orchestration:** Google Cloud Agent Builder
- **Data + MCP:** MongoDB collections — `mower_models`, `yards`, `deployment_plans` — via the **MongoDB MCP server**

## Submission requirements (Devpost)

- [x] Hosted project URL — **https://lawn.forenly.ai**
- [x] Public repository
- [x] LICENSE detectable at the top of the repo — Apache-2.0
- [x] ~3 minute demo video — served at [lawn.forenly.ai/walkthrough-videos](https://lawn.forenly.ai/walkthrough-videos) (video binaries live on the deployment, not in git)
- [x] Selected partner track — **MongoDB MCP**
- [ ] Completed Devpost submission form

## Tests

Hermetic unit/integration suite (no network, no live MongoDB, no Vertex calls —
external services are monkeypatched):

```bash
cd agent
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q
```

## Status

✅ Live at **https://lawn.forenly.ai** — map-drawn yard input, geo enrichment
(slope + soil), Gemini tool-loop recommendation grounded in the MongoDB
registry, and a 4-phase deployment rollout. Issues, milestones, and design
notes are tracked in this repo's Issues tab.

## Contributing

Contributions welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md). Day-to-day
discussion happens on the project **Discord**.

## License

[Apache License 2.0](./LICENSE)
