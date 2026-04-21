---
name: omh-autopilot
description: >
  Full autonomous pipeline from idea to verified code. Composes deep-interview,
  ralplan, and ralph into 6 phases: Requirements → Planning → Execution → QA →
  Validation → Cleanup. One phase step per invocation — the caller re-invokes
  until complete. Detects existing artifacts to skip completed phases.
version: 2.0.0
tags: [autopilot, pipeline, autonomous, end-to-end, composition]
category: omh
metadata:
  hermes:
    requires_toolsets: [terminal, omh]
---

# OMH Autopilot — End-to-End Autonomous Pipeline

## When to Use

- End-to-end feature implementation from idea to verified, reviewed code
- The user says: "autopilot", "build me", "handle it all", "e2e this"

## When NOT to Use

- Single-file changes or trivial tasks (just do them)
- You want to stay in one continuous session (autopilot is multi-session)
- You only need planning (omh-ralplan) or execution (omh-ralph)

## Prerequisites

- The `omh` plugin must be installed (`~/.hermes/plugins/omh/`)

## Architecture: One Phase Step Per Invocation

Each autopilot invocation reads state, does ONE unit of work, exits. The caller re-invokes.
This preserves fresh context at every level — including during the ralph loop.

```
Invocation 1:   Phase 0 — requirements (or skip)
Invocation 2:   Phase 1 — planning (or skip)
Invocations 3-N: Phase 2 — ralph iterations (one per call)
Invocation N+1: Phase 3 — QA cycle         [FRESH SESSION]
Invocation M:   Phase 4 — validation round  [FRESH SESSION]
Final:          Phase 5 — cleanup → complete
```

See `references/caller-examples.md` for how to drive the loop.

## Procedure

### Step 0: Resolve Instance and Acquire Lock

Autopilot drives a goal through spec → plan → ralph → QA → validation.
Two autopilot sessions on the same goal would race on `autopilot`,
`ralph`, and `ralph-tasks` state simultaneously. Use per-instance state
+ advisory lock.

1. **Resolve `instance_id`** in this order:
   - If a confirmed spec exists at `.omh/specs/{name}-spec.md`, use
     `instance_id = "{name}"`.
   - Else if a plan exists at `.omh/plans/ralplan-{slug}.md`, use
     `instance_id = "{slug}"`.
   - Else derive from the goal: `instance_id = kebab(goal)[:60]`.
2. **Acquire the autopilot lock**:
   ```
   lock = omh_state(action="lock", mode="autopilot",
                    lock_key="{instance_id}",
                    session_id="{HERMES_SESSION_ID or uuid}",
                    holder_note="autopilot driving {goal_or_plan}")
   ```
   On `acquired=false`, report `held_by`, offer wait/cancel/different
   goal. Stale-pid auto-release applies.
3. **Pass `instance_id` to every `omh_state` call** in this invocation
   (autopilot, ralph, ralph-tasks).
4. **When dispatching to ralph in Phase 2**, pass the same
   `instance_id` in the delegation context so the ralph subagent
   acquires `mode="ralph"` lock on the same slug.
5. **Release the autopilot lock at every exit point** (paused,
   blocked, complete, exception):
   ```
   omh_state(action="unlock", mode="autopilot",
             lock_key="{instance_id}",
             session_id="{HERMES_SESSION_ID or uuid}")
   ```

> **Singleton fallback (legacy).** Omitting `instance_id` writes
> `.omh/state/autopilot-state.json` and skips locking. Acceptable only
> when running one autopilot at a time.

### On Every Invocation: Dispatch

```
state = omh_state(action="read", mode="autopilot", instance_id="{instance_id}")
```

- **Not found**: Fresh start → Smart Detection (below)
- **Found**: Check `context_checkpoint` flag → if true, clear it and exit (phase boundary)
- Check staleness: `state.stale = true` → warn, offer fresh start
- Check pause: if `pause_after_phase` matches current completed phase → set phase="paused", exit
- Dispatch to current phase handler

### Smart Detection (Fresh Start)

When no autopilot state exists, detect artifacts:

1. Confirmed spec in `.omh/specs/*-spec.md` → create state at Phase 1
2. Consensus plan in `.omh/plans/ralplan-*.md` → create state at Phase 2
3. Ralph complete (`omh_state(action="check", mode="ralph", instance_id="{instance_id}")` → phase="complete") → create state at Phase 3
4. Nothing → create state at Phase 0

Check for active ralph: `omh_state(action="check", mode="ralph", instance_id="{instance_id}")` → if active, warn about existing session.

```
omh_state(action="write", mode="autopilot", instance_id="{instance_id}", data={
    "phase": "requirements", "goal": "...", "ralph_iteration": 0,
    "qa_cycle": 0, "max_qa_cycles": 5, "validation_round": 0,
    "max_validation_rounds": 3, "validation_verdicts": {},
    "skip_qa": false, "skip_validation": false, "pause_after_phase": null
})
```

### Phase 0: Requirements

**Goal**: Ensure a confirmed spec exists.

1. Check `.omh/specs/*-spec.md` with `status: confirmed` → found? Set `spec_file`, advance to Phase 1, exit
2. Not found — assess input:
   - **Concrete** (file paths, function names, specific tech): generate inline spec, advance
   - **Vague**: Load `omh-deep-interview` and follow it. **This phase is interactive.**
3. Update state: `phase: "planning"`, `spec_file: "<path>"`. Exit.

**For fully autonomous runs**: run `omh-deep-interview` separately first.

### Phase 1: Planning

**Goal**: Ensure a consensus plan exists.

1. Check `.omh/plans/ralplan-*.md` → found? Set `plan_file`, advance to Phase 2, exit
2. Not found: Load `omh-ralplan`, follow its procedure with the spec as input
3. Update state: `phase: "execution"`, `plan_file`, `ralph_iteration: 0`, `context_checkpoint: true`. Exit.

### Phase 2: Execution (Ralph Iterations)

Each invocation performs **exactly ONE ralph iteration**:

1. Run one ralph iteration via `delegate_task` with the omh-ralph skill context:
   ```
   delegate_task(goal="[omh-role:executor] Follow the omh-ralph skill procedure:
     read state, pick the next incomplete task, execute it, verify, update state, exit.",
     context="<current ralph state + plan file contents>")
   ```
2. After ralph completes its step, check ralph status:
   ```
   ralph = omh_state(action="check", mode="ralph", instance_id="{instance_id}")
   ```
   - `active=true` → increment `ralph_iteration`, exit (caller re-invokes)
   - `phase="complete"` → advance: `phase: "qa"`, `context_checkpoint: true`, exit
   - `phase="blocked"` → set autopilot `phase: "blocked"`, report, exit

### Phase 3: QA Cycling

Each invocation performs **ONE QA cycle**. Starts in fresh session (context_checkpoint).

If `skip_qa: true` → advance to Phase 4, exit.

1. Gather evidence using the project's actual build/test/lint commands (check for
   Makefile, package.json, Cargo.toml, pyproject.toml, etc. to determine the right commands):
   ```
   evidence = omh_gather_evidence(commands=["<build>", "<test>", "<lint>"])
   ```
2. If `evidence.all_pass` → advance: `phase: "validation"`, `context_checkpoint: true`, exit
3. If failures:
   - Increment `qa_cycle`. Check 3-strike on `qa_error_history`. If triggered → phase="blocked", exit
   - If `qa_cycle > max_qa_cycles` (default 5) → phase="blocked", exit
   - Delegate diagnosis to architect subagent (read-only)
   - Delegate fix to executor subagent
   - Update state, exit (next invocation re-runs QA)

### Phase 4: Multi-Reviewer Validation

Each invocation performs **ONE validation round**. Starts in fresh session.

If `skip_validation: true` → advance to Phase 5, exit.

1. Gather evidence using the project's actual build/test commands:
   ```
   evidence = omh_gather_evidence(commands=["<build>", "<test>"])
   ```
2. Delegate 3 parallel reviews (exactly 3 = Hermes concurrent limit):
   ```
   delegate_task(tasks=[
       {goal: "[omh-role:architect] Architectural review:\n{spec + plan}", context: "{evidence}"},
       {goal: "[omh-role:security-reviewer] Security review:\n{changed files list}", context: "{evidence}"},
       {goal: "[omh-role:code-reviewer] Code quality review:\n{changed files list}", context: "{evidence}"}
   ])
   ```
3. Record verdicts in `validation_verdicts`
4. All APPROVE → advance to Phase 5, exit
5. Any REQUEST_CHANGES → delegate fix to executor, increment `validation_round`, exit
6. If `validation_round > max_validation_rounds` (default 3) → phase="blocked", exit

### Phase 5: Cleanup

1. Set `phase: "complete"` (safety — if interrupted, re-invocation retries cleanup)
2. Delete state files:
   ```
   omh_state(action="clear", mode="autopilot", instance_id="{instance_id}")
   omh_state(action="clear", mode="ralph", instance_id="{instance_id}")
   omh_state(action="clear", mode="ralph-tasks", instance_id="{instance_id}")
   ```
3. Preserve: `.omh/logs/`, `.omh/plans/`, `.omh/specs/`
4. Report completion summary: goal, phases completed, ralph iterations, QA cycles, validation rounds

## State Management

All state via `omh_state` tool. Atomic writes and staleness handled automatically.

## Sentinel Convention

```
omh_state(action="check", mode="autopilot", instance_id="{instance_id}")
→ {exists, active, phase, stale}
```

## Pitfalls

- **Don't loop ralph in a single session.** Each ralph iteration is a separate invocation. Context exhaustion is real.
- **Don't reimplement ralph.** Load the skill, follow its procedure.
- **Phase boundaries = fresh sessions.** Respect `context_checkpoint`.
- **Don't skip QA.** Ralph verifies per-task. QA catches integration issues.
- **Phase 0 is interactive** if no spec exists. Pre-create specs for automated runs.
- **3 subagent limit.** Phase 4 uses all 3 slots for parallel review.
