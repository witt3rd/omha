---
name: omh-ralph
description: >
  Verified execution loop: picks the next task from a plan, delegates to an executor
  subagent, verifies completion with fresh evidence, and updates state. One task per
  invocation — the caller re-invokes until all tasks pass. Enforces the Iron Law:
  every change must be verified through builds, tests, and independent review.
version: 2.0.0
tags: [execution, verification, persistence, iron-law, loop]
category: omh
metadata:
  hermes:
    requires_toolsets: [terminal, omh]
---

# OMH Ralph — Verified Execution (v2)

> **Requires the OMH plugin.** Install `plugins/omh/` from this repo to
> `~/.hermes/plugins/omh/`.

## When to Use

- You have a plan (from omh-ralplan or manual) and need verified execution
- The user says: "ralph", "don't stop", "until done", "must complete", "keep going"
- You need guaranteed verification — not just "looks done" but evidence-backed completion
- Multi-step implementation where each task must be independently verified

## When NOT to Use

- No plan or spec exists (use omh-deep-interview and/or omh-ralplan first)
- Trivial single-file changes (just do them directly)
- The user explicitly wants to skip verification

## Architecture: One Task Per Invocation

Each ralph invocation does ONE unit of work and exits. The caller re-invokes for
the next task. This eliminates context window exhaustion and makes every invocation
a clean checkpoint.

```
Invocation N:  read state → pick task → execute → verify → update state → EXIT
Invocation N+1: read state → pick next task → execute → verify → update state → EXIT
...
Final invocation: all tasks pass → architect review → mark complete → EXIT
```

## Procedure

### Step 1: Read State

```
state = omh_state(action="read", mode="ralph")
```

- **`state.exists=false`**: Fresh start — go to Step 2 (Planning Gate).
- **`state.data.active=true`**: Resume — go to Step 3.
- **`state.data.phase="complete"`**: Report completion. Ask if user wants fresh start.
- **`state.data.phase="blocked"`**: Report blockers. Ask if issues are resolved.
- **`state.data.active=false`, `phase="cancelled"`**: Report cancellation. Offer resume.

Check for cancel signal:
```
cancel = omh_state(action="cancel_check", mode="ralph")
```
If `cancel.cancelled=true`: set phase="cancelled", write state, exit.

Check staleness: if `state.stale=true`, warn the user and offer to continue or fresh start.

Increment `state.data.iteration`. If `iteration > max_iterations` (default 100):
write `phase="blocked"`, report "Max iterations reached", exit.

### Step 2: Planning Gate

Ralph MUST NOT execute without a plan. Check sources in order:

1. `omh_state(action="check", mode="ralph-tasks")` → `exists=true` — already parsed, skip to Step 3
2. `.omh/plans/ralplan-*.md` — parse into ralph-tasks state: `omh_state(action="write", mode="ralph-tasks", data={...})`
3. `.omh/plans/ralph-plan.md` — parse into ralph-tasks state
4. Nothing found → tell user: "No plan found. Run `omh-ralplan` first."

**Plan parsing rules:**
- Extract numbered tasks with titles, descriptions, and acceptance criteria
- Reject generic criteria like "implementation is complete" — must be testable
- Enforce atomicity: split multi-part tasks into separate entries
- Assign priorities by dependency order (no-dependency tasks first)
- Set all tasks to `passes: false`

Write initial state:
```
omh_state(action="write", mode="ralph", data={
  "active": true, "phase": "execute", "iteration": 0,
  "session_id": "<uuid>", "max_iterations": 100,
  "task_prompt": "<original user request>",
  "current_task_id": null,
  "started_at": "<ISO 8601 timestamp>",
  "project_path": "<absolute path to project root>",
  "files_modified": [],
  "error_history": [],
  "completed_task_learnings": []
})
```

### Step 3: Pick Next Task

Read task list:
```
tasks = omh_state(action="read", mode="ralph-tasks")
```

1. If ALL tasks have `passes: true` → go to Step 7 (Final Review)
2. Find eligible tasks: `passes=false` AND all dependencies met
3. If no eligible task but incomplete tasks remain → dependency deadlock → set
   `phase="blocked"`, write state, exit
4. Among eligible tasks, pick by priority (lowest number first)

**Parallel execution:** if 2-3 independent tasks are eligible (no shared file
footprint, no dependency between them), batch them into one `delegate_task` call.

### Step 4: Execute

Delegate to an executor subagent:

```
delegate_task(
    goal="[omh-role:executor] Implement this task:\n\n{task.title}\n{task.description}\n\nAcceptance Criteria:\n{task.acceptance_criteria}",
    context="Project Context:\n{tech stack, conventions, relevant paths}\n\nPrevious Feedback (if retry):\n{task.verifier_verdict}\n\nLearnings from prior tasks:\n{state.data.completed_task_learnings}"
)
```

The `[omh-role:executor]` marker in the goal causes the OMH plugin to automatically
inject the executor role prompt into the subagent's system prompt — no inlining needed.
(Fallback without plugin: replace marker with `omh_state(action="load_role", role="executor")`
and pass the returned prompt text in context.)

Parse the executor's response: **COMPLETE** → Step 5, **PARTIAL** → Step 5,
**BLOCKED** → record blocker, add discovered task if needed, update state, exit.

### Step 5: Verify

**Part A: Gather evidence**

```
evidence = omh_gather_evidence(commands=[
    "{project build command}",
    "{project test command}",
    "{project lint command}"
])
```

Use the project's actual build/test/lint commands. The tool captures output,
enforces timeouts, and returns `{results, all_pass, summary}`.

**Part B: Delegate to verifier**

```
delegate_task(
    goal="[omh-role:verifier] Verify whether this task's acceptance criteria are met:\n\n{task.title}\n{task.acceptance_criteria}\n\nExecutor Report:\n{task.executor_report}",
    context="Evidence:\n{evidence.results}"
)
```

Parse the verifier's response:
- **APPROVE / PASS**: Set `task.passes = true`. Append to learnings:
  `{task_id, summary, files_changed, gotchas}`. Append to `.omh/logs/ralph-progress.md`.
- **REQUEST_CHANGES / FAIL**: Record `task.verifier_verdict`. Check 3-strike rule (Step 6).

### Step 6: Error Handling

**3-Strike Circuit Breaker:** Construct error fingerprint `{task_id, category, error_key}`.
Add to `task.error_fingerprints`. If 3 fingerprints share the same `category + error_key`:
mark task blocked, log the error, continue to next eligible task on next invocation.
If ALL remaining tasks are blocked: write `phase="blocked"`, report, exit.

**Cancel detection** (if user says "stop", "cancel", "abort"):
```
omh_state(action="cancel", mode="ralph", reason="user request")
```
Then write `phase="cancelled"` to state, exit with resume instructions.

### Step 7: Final Review

When all tasks have `passes: true`:

```
evidence = omh_gather_evidence(commands=["{build command}", "{test command}"])

delegate_task(
    goal="[omh-role:architect] Review the complete implementation for architectural soundness.\n\nOriginal Plan:\n{source plan text}\n\nTasks Completed:\n{summary of all tasks + learnings}",
    context="Evidence:\n{evidence.results}\n\nFiles Changed Across All Tasks:\n{aggregate file list}"
)
```

- **APPROVE**: Write `{active: false, phase: "complete"}`, clear state files, keep progress log.
- **REQUEST_CHANGES**: Add new tasks with `discovered: true`, set `phase="execute"`.

### Step 8: Update State and Exit

After every action:
```
omh_state(action="write", mode="ralph", data={...updated state...})
```

Exit cleanly. The caller re-invokes for the next iteration.

## Pitfalls

- **Never skip the planning gate.** No plan = no execution.
- **Never trust executor claims without verifier evidence.** The verifier must see `omh_gather_evidence` output.
- **Don't run evidence inside the verifier delegation.** Gather evidence BEFORE delegating.
- **Don't conflate verifier and architect.** Different jobs, different prompts, different phases.
- **Respect the 3-strike rule.** Same error 3 times → surface the fundamental issue.
- **Feed learnings forward.** Include `completed_task_learnings` in every executor delegation.
- **Use `[omh-role:NAME]` markers** — the OMH plugin injects role prompts automatically into subagent sessions. Never inline role prompt text manually. Available roles: executor, verifier, architect, planner, critic, analyst, security-reviewer, code-reviewer, test-engineer, debugger. Fallback without plugin: `omh_state(action="load_role", role="NAME")` and pass returned prompt in context.

## Sentinel Convention

Other skills detect ralph status:
- `omh_state(action="check", mode="ralph")` → `{exists, active, phase, stale}`
- `phase="complete"` → ralph finished successfully
- `phase="blocked"` → ralph needs intervention
