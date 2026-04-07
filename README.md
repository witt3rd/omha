# Oh My Hermes Agent (OMHA)

Multi-agent orchestration skills for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Inspired by [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode), rebuilt natively for Hermes primitives.

## What This Is

A collection of composable skills that bring structured multi-agent workflows to Hermes Agent:

- **omha-ralplan** — Consensus planning: Planner → Architect → Critic loop until agreement
- **omha-deep-interview** — Ambiguity gating with mathematical scoring before execution
- **omha-ralph** — Persistence loop: execute → verify → loop until verified complete
- **omha-autopilot** — Full pipeline: interview → plan → implement → QA → validate

Each skill uses Hermes's `delegate_task` for isolated subagent execution and file-based state for resumability. No code changes to Hermes Agent required.

## Install

```bash
# Add as a tap (one-time)
hermes skills tap add witt3rd/omha

# Install individual skills
hermes skills install omha-ralplan
hermes skills install omha-deep-interview
hermes skills install omha-ralph
hermes skills install omha-autopilot
```

## How They Compose

```
omha-deep-interview  →  spec (ambiguity ≤ 0.2)
    ↓
omha-ralplan         →  consensus plan (Planner/Architect/Critic approved)
    ↓
omha-autopilot       →  skips planning phases, starts at execution
    ↓ (internally uses)
omha-ralph           →  persistence loop until verified
```

Each skill works standalone or composes with the others. Autopilot detects existing specs and plans, skipping phases that are already complete.

## Architecture

All skills share a common set of role prompts (stored as skill `references/`) that give subagents precise behavioral instructions. State is written to `.omha/` in the project directory for resumability.

See [docs/architecture.md](docs/architecture.md) for details.

## Requirements

- Hermes Agent v0.7.0+
- No additional dependencies

## License

MIT
