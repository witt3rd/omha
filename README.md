# Oh My Hermes (OMH)

Multi-agent orchestration skills for [Hermes Agent](https://github.com/NousResearch/hermes-agent),
inspired by [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode)
and rebuilt natively for Hermes primitives.

OMH provides composable skills for consensus planning, requirements
interviewing, and verified execution — plus an optional plugin that adds
hook-based role injection, atomic state management, and evidence gathering.
Skills work standalone with zero dependencies.

| Skill | What It Does |
|-------|--------------|
| **omh-ralplan** | Consensus planning: Planner → Architect → Critic debate until agreement |
| **omh-deep-interview** | Socratic requirements interview with coverage tracking |
| **omh-ralph** | Verified execution: implement → verify → iterate until done |
| **omh-autopilot** | Full pipeline composing all three skills end-to-end |

## Install

```bash
hermes skills tap add witt3rd/oh-my-hermes
hermes skills install omh-ralplan omh-deep-interview omh-ralph omh-autopilot
```

Or copy `skills/<name>/` to `~/.hermes/skills/omh/` manually.

For the optional plugin: install `plugins/omh/` to `~/.hermes/plugins/omh/`
(requires Python 3.10+ and `pyyaml`).

## Getting Started

- **Just need a plan?** → `omh-ralplan`
- **Vague idea?** → `omh-deep-interview` then `omh-ralplan`
- **Have a plan, need execution?** → `omh-ralph`
- **End-to-end?** → `omh-autopilot`

OMH self-seeds a `.omh/` directory in the project on first use (with the
plugin installed) — including a README explaining the convention and a
`.gitignore` pre-configured for selective sharing. To scaffold up-front
without running a workflow, call `omh_state(action="init")`.

## Requirements

Hermes Agent v0.7.0+. The plugin additionally requires Python 3.10+ and
`pyyaml`.

## Documentation

- [`docs/concepts.md`](docs/concepts.md) — How the four skills work
- [`docs/plugin.md`](docs/plugin.md) — The v2 plugin (roles, hooks, tools)
- [`docs/omc-comparison.md`](docs/omc-comparison.md) — Origins and design choices vs OMC
- [`docs/hermes-constraints.md`](docs/hermes-constraints.md) — How OMH works around Hermes limits
- [`docs/gaps.md`](docs/gaps.md) — What's not built yet
- [`ROADMAP.md`](ROADMAP.md) — Versions and direction

## License

MIT
