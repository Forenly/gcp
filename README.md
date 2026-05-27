# gcp — Agentic Change & Configuration Registry (Google Cloud + MongoDB)

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)

> Submission for the **Google Cloud Rapid Agent Hackathon** — "Building Agents for Real-World Challenges". Partner track: **MongoDB MCP**.

## The problem

When an engineering or operational change is proposed, the slow part isn't deciding —
it's recalling what changed before, what configuration items it touched, and what plan
worked. That knowledge is scattered across tickets, spreadsheets, and people's heads.

## What we're building

An agent that turns a **MongoDB-backed registry** of configuration items, change requests,
and past change plans into a living advisor. Given a new change/incident, the agent:

1. Recalls similar past changes and the plans that resolved them.
2. Recommends a disposition and drafts a plan (affected items, effectivity, risk).
3. Writes the new record back to the registry with an audit trail.

The registry is exposed via the **MongoDB MCP server**, so the agent reads/writes it through MCP.

## How it's built

- **Model:** Gemini (Google Cloud)
- **Orchestration:** Google Cloud Agent Builder
- **Data + MCP:** MongoDB (collections: `configuration_items`, `change_requests`, `change_plans`, `audit_log`) via **MongoDB MCP server**

## Submission requirements (Devpost)

- [ ] Hosted project URL
- [x] Public repository
- [x] LICENSE detectable at the top of the repo — Apache-2.0
- [ ] ~3 minute demo video
- [x] Selected partner track — **MongoDB MCP**
- [ ] Completed Devpost submission form

## Status

🚧 Early development. Issues, milestones, and design notes are tracked here.

## Contributing

Contributions welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md). Day-to-day discussion happens on the project **Discord**.

## Team

**Forenly AI Systems** · [github.com/forenly-ai-systems](https://github.com/forenly-ai-systems)

## License

[Apache License 2.0](./LICENSE)
