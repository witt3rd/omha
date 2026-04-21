# Project Context: oh-my-hermes (OMH)

## What OMH Is

OMH is a Hermes plugin + skill bundle that adds verified-execution and
multi-agent debate workflows on top of the Hermes agent runtime. It ships:

- A Python plugin at `plugins/omh/` providing tools: `omh_state`,
  `omh_gather_evidence`, role injection, and (soon) `omh_delegate`.
- A set of skills under `plugins/omh/skills/`: `omh-ralplan` (consensus
  planning via Planner/Architect/Critic debate), `omh-ralph` (verified
  execution loop), `omh-autopilot` (idea→verified-code pipeline),
  `omh-deep-interview` (Socratic spec elicitation).

## Architecture Snapshot

**Plugin tools (Python):**
- `omh_state.py` — atomic read/write/cancel for `.omh/state/{mode}-state.json`.
  Pattern: write to `.tmp.{uuid}` → fsync → `os.replace`. Wraps data in
  `_meta` envelope `{written_at, mode, schema_version}`.
- `omh_config.py` — loads `plugins/omh/config.yaml`, caches via
  `_config_cache`. Recently fixed (Bug 2): `_state_dir()` now resolves
  relative paths against `config["project_root"]` (or cwd) and `.resolve()`s
  to absolute — immune to cwd drift.
- `tools/state_tool.py` — Hermes handler registration that dispatches
  `omh_state(action=...)` calls.
- `tools/evidence_tool.py` — runs allowlisted commands and captures output.
  Already uses the project_root resolution pattern; reference for new code.

**Skills (markdown):**
Skills are procedural specs, not code. They tell the orchestrator agent
what to do. Currently they call `delegate_task` directly in their prose
(e.g. `omh-ralplan/SKILL.md` invokes `delegate_task(goal=..., context=...)`
to dispatch role-prompted subagents).

**Convention (just landed in this branch):**
- `.omh/state/` — gitignored, ephemera (per-mode state JSON).
- `.omh/research/` — tracked, decision artifacts (subagent outputs, briefs).
- `.omh/plans/` — tracked, ralplan output.
- `.omh/specs/` — tracked, deep-interview output.
- `.omh/README.md` + `.omh/.gitignore` — auto-seeded on first state write.

## What's Broken

`delegate_task` is a fragile in-memory boundary. Two failure modes
(omh-self-flakiness.md):

1. **Parent loses subagent output mid-write.** Result returns to memory,
   parent must `write_file` to persist, parent stream drops first → result
   gone. Recovery requires hand-spelunking `~/.hermes/state.db`.

2. **Subagent stalls on its own write_file.** Internal output exists,
   subagent never returns. 14.8 minutes of work, 284 tokens, nothing on
   disk. Today: truly lost.

OMH skills (ralplan, ralph, autopilot) all build on `delegate_task` with no
insurance. We're proposing a wrapper `omh_delegate` that persists subagent
outputs to disk before returning to the caller.

## Constraints for New Code

- **Path resolution:** Always anchor relative paths against `project_root`
  (config) or `Path.cwd().resolve()`. Never raw `Path(".omh/...")`.
- **Atomicity:** New writes mirror omh_state's tmp→fsync→replace pattern.
- **Backward compatibility:** Existing OMH skills must keep working. New
  tool is additive; replacement of `delegate_task` calls happens in a
  follow-up migration.
- **Hermes contract limits:** Subagents can't load skill files — role
  prompts must be inlined into the `delegate_task` context arg.
  Subagents have no access to the parent's conversation; goal+context
  must be self-contained.

## Tests

`plugins/omh/tests/` — 164 passing. Use pytest. Conftest pattern:
isolate state via `monkeypatch.chdir(tmp_path)` + monkeypatch
`omh_config_module._config_cache`. New tests should mirror existing
fixture style.

## Why This Matters

This is dogfood. The omh_delegate design is itself being run through
omh-ralplan — the very skill that triggered the failure modes. If the
design works, ralplan-on-self produces a vetted plan with no losses
(belt-and-suspenders: every subagent return persisted to
`.omh/research/ralplan-omh-delegate/` immediately on receipt, before the
orchestrator does anything else with it).
