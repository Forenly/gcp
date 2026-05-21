# Forenly · Lawn Mower Deployment Advisor

> Submission for the **Google Cloud Rapid Agent Hackathon** — "Building Agents for Real-World Challenges"

## The problem

Before a robot is physically deployed into a new scene, operators need to know
what configuration it will actually require to work there. Today this is mostly
trial-and-error on-site.

## What we're building

An agent that runs a **pre-deployment simulation** of the target scene and
outputs the configuration the real robot will need at runtime.

Given a description of the deployment scene, the agent:

1. Sets up a runtime simulation that hosts the robot
2. Plans the steps the robot will need to take
3. Returns the configuration required for the implementation plan

## How it's built

- **Model:** Gemini (Google Cloud)
- **Orchestration:** Google Cloud Agent Builder
- **Partner MCP integration:** **MongoDB MCP** — locked 2026-05-19 (registry + yard profiles + deployment plans store)

## Submission requirements (Devpost)

- [ ] Hosted project URL
- [x] Public repository
- [ ] LICENSE file detectable at the top of the repo — ✅ Apache-2.0
- [ ] ~3 minute demo video
- [ ] Selected partner track
- [ ] Completed Devpost submission form

## Status

🚧 Early development. Issues, milestones, and design notes are tracked here.

## Team

**Forenly AI Systems** · [github.com/forenly-ai-systems](https://github.com/forenly-ai-systems)

Want to contribute? See [CONTRIBUTING.md](./CONTRIBUTING.md).

## Coordination

Day-to-day discussion happens in the **#lawn-prs** Discord channel.

## License

[Apache License 2.0](./LICENSE)
