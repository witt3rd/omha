# OMHA Architecture

## Composition Model

OMHA skills compose as layers, each usable standalone or as part of a larger pipeline:

```
omha-deep-interview (requirements)
        ↓ produces spec
omha-ralplan (consensus planning)
        ↓ produces plan
omha-ralph (persistence execution)
        ↓ produces verified code
omha-autopilot (full pipeline — composes all three)
```

## Primitives

All OMHA skills are built on three Hermes primitives:

1. **delegate_task** — Spawn isolated subagents with role-specific context
2. **File-based state** — `.omha/` directory for persistence and inter-phase handoffs
3. **todo** — Session-level task tracking for visibility

No custom tools, no code changes to Hermes Agent, no plugins required.

## Role Prompts

Shared role prompts live in `omha-ralplan/references/` (since ralplan is the
bootstrap skill). Each prompt defines:

- Responsibilities
- Working protocol
- Output format
- Principles

Roles: planner, architect, critic, executor, analyst, security-reviewer,
test-engineer, debugger

When delegating, the orchestrating skill loads the role prompt and passes it
in the `context` field of `delegate_task`. The subagent receives a fresh
context with only the role prompt + task description + project context.

## State Convention

```
.omha/
├── state/     # Active mode state (JSON) — deleted on completion
├── plans/     # Consensus plans (Markdown) — persisted
├── specs/     # Interview specifications (Markdown) — persisted
└── logs/      # Audit trail
```

Skills check for existing state on invocation. If found, they offer to
resume from the last checkpoint rather than starting over.

## Hermes Constraints

| Constraint | Impact | Mitigation |
|---|---|---|
| 3 concurrent subagents | Phase 4 validation fits exactly (architect + security + code reviewer) | Batch larger parallel work into groups of 3 |
| No recursive delegation | Subagents can't spawn their own subagents | All orchestration happens at the top level |
| Prompt-based persistence | Ralph can't mechanically prevent session exit | Strong instructions + state files for resume |
| Subagents lack execute_code | Children reason step-by-step, can't batch | Orchestrator uses execute_code, children use tools directly |
