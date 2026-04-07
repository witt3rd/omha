---
name: omha-ralph
description: >
  Persistence loop that executes tasks and verifies completion through an independent reviewer.
  Loops until verified complete or max iterations reached. Enforces the Iron Law: every change
  must be validated through builds, tests, and review before marking done. Use for tasks that
  must reach verified completion.
version: 0.1.0
tags: [persistence, verification, loop, iron-law]
category: omha
metadata:
  hermes:
    requires_toolsets: [terminal]
---

# OMHA Ralph — Persistence Loop

## Status: STUB — To Be Built

This skill will be designed using `omha-ralplan` consensus planning.

## When to Use

- When a task must reach verified completion (not just "looks done")
- For multi-step implementation work where partial completion is unacceptable
- When the user says: "ralph", "don't stop", "until done", "must complete", "keep going"

## Planned Design

### Core Loop
```
1. Read task spec + acceptance criteria (planning gate: must exist)
2. Execute implementation via delegate_task (executor role)
3. Verify via delegate_task (architect role — independent review)
4. Run builds and tests
5. If verification fails → incorporate feedback, loop to step 2
6. If same error repeats 3× → STOP and surface the fundamental issue
7. On success → write completion state, clean exit
```

### State Management
Track in `.omha/state/ralph-state.json`:
- Current iteration number
- Phase within iteration
- Error history (for 3-strike detection)
- Files modified

### Iron Law Verification Gate
Every iteration must pass ALL of:
1. Build succeeds (if applicable)
2. Tests pass (if applicable)
3. Independent architect review approves

### Prompt-Based Persistence
Since Hermes has no mechanical stop-prevention hook, ralph relies on skill
instructions to keep the agent iterating. The skill should:
- Use strong instructional language ("you MUST continue until verified")
- Track state so interruptions can resume
- Report progress clearly so the user sees momentum

## TODO
- [ ] Design via ralplan consensus
- [ ] Implement core loop with state tracking
- [ ] Implement 3-strike error detection
- [ ] Implement verification gate
- [ ] Test resumability after interruption
