---
name: omha-autopilot
description: >
  Full autonomous pipeline from idea to verified working code. Composes deep-interview,
  ralplan, ralph, and existing review skills into a 5-phase pipeline. Detects existing
  specs and plans to skip completed phases. Use for end-to-end feature work.
version: 0.1.0
tags: [autopilot, pipeline, autonomous, end-to-end]
category: omha
metadata:
  hermes:
    requires_toolsets: [terminal]
---

# OMHA Autopilot — Full Autonomous Pipeline

## Status: STUB — To Be Built

This skill will be designed using `omha-ralplan` consensus planning after
the component skills (deep-interview, ralph) are implemented.

## When to Use

- End-to-end feature implementation from idea to working code
- When the user says: "autopilot", "build me", "handle it all", "e2e this"
- When you want the full pipeline: requirements → plan → implement → QA → validate

## Planned Design

### 5-Phase Pipeline
```
Phase 0: Requirements  → omha-deep-interview (if goal is vague)
                         Skip if .omha/specs/ already has a matching spec
Phase 1: Planning      → omha-ralplan consensus (Planner/Architect/Critic)
                         Skip if .omha/plans/ already has a matching plan
Phase 2: Execution     → omha-ralph (persistence loop with parallel tasks)
                         delegate_task with executor role per task
Phase 3: QA            → Build + lint + test cycle, up to 5 iterations
                         Uses existing test-driven-development skill patterns
Phase 4: Validation    → Parallel review via delegate_task (up to 3 concurrent):
                         - Architect (completeness review)
                         - Security reviewer
                         - Code reviewer
                         All must approve
Phase 5: Cleanup       → Delete .omha/state/ files, report summary
```

### Smart Phase Detection
On invocation, check for existing artifacts:
- `.omha/specs/` → skip Phase 0
- `.omha/plans/` → skip Phase 1
- `.omha/state/autopilot-state.json` → resume from last completed phase

### State Management
Track in `.omha/state/autopilot-state.json`:
- Current phase
- Phase results (spec file, plan file, etc.)
- QA iteration count
- Validation verdicts

## Dependencies
- `omha-deep-interview` (Phase 0)
- `omha-ralplan` (Phase 1)
- `omha-ralph` (Phase 2)
- Hermes built-in: `requesting-code-review`, `systematic-debugging`, `test-driven-development`

## TODO
- [ ] Build omha-deep-interview first
- [ ] Build omha-ralph first
- [ ] Design autopilot composition via ralplan consensus
- [ ] Implement phase detection and skip logic
- [ ] Implement the full pipeline
- [ ] Test end-to-end on a real feature
