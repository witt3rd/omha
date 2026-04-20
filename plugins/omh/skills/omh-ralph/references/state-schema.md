# Ralph State Schema

## File Layout

```
.omh/
├── state/
│   ├── ralph-state.json        # Loop state + cancel signal (deleted on completion)
│   ├── ralph-tasks.json        # Task list with acceptance criteria (deleted on completion)
├── logs/
│   └── ralph-progress.md       # Append-only execution log (preserved)
```

## ralph-state.json

```json
{
  "active": true,
  "session_id": "uuid-of-creating-session",
  "iteration": 1,
  "max_iterations": 100,
  "phase": "execute|verify|final-review|complete|blocked|cancelled",
  "task_prompt": "original task/goal text",
  "current_task_id": "T-001",
  "started_at": "2026-04-07T06:30:00Z",
  "last_updated_at": "2026-04-07T06:35:00Z",
  "project_path": "/path/to/project",
  "awaiting_confirmation": false,
  "awaiting_confirmation_set_at": null,
  "files_modified": [],
  "error_history": [],
  "completed_task_learnings": [
    {
      "task_id": "T-001",
      "summary": "Implemented auth module using JWT",
      "files_changed": ["src/auth.py", "tests/test_auth.py"],
      "gotchas": "PyJWT requires the cryptography package for RS256"
    }
  ]
}
```

### Fields

- **active**: `true` while ralph is running, `false` on completion/blocked/cancelled
- **session_id**: UUID generated on fresh start. On resume, checked against current session — mismatch produces a warning (different sessions are expected in one-task-per-invocation)
- **iteration**: Incremented each invocation. Hard cap at max_iterations.
- **max_iterations**: Default 100. Configurable. Hard cap (no auto-extend — no stop hook to enforce it)
- **phase**: Current lifecycle phase
- **awaiting_confirmation**: When ralph needs user input, sets this + exits. Re-invocation checks the flag. 2-minute TTL via awaiting_confirmation_set_at.
- **completed_task_learnings**: Discoveries from prior tasks, fed into subsequent executor contexts. Grows monotonically — never trimmed.

## ralph-tasks.json

```json
{
  "source_plan": ".omh/plans/ralplan-consensus-my-project.md",
  "tasks": [
    {
      "id": "T-001",
      "title": "Implement user authentication",
      "description": "Add JWT-based auth with login and token refresh endpoints",
      "acceptance_criteria": [
        "POST /auth/login returns JWT token for valid credentials",
        "POST /auth/refresh returns new token for valid refresh token",
        "Invalid credentials return 401"
      ],
      "passes": false,
      "priority": 1,
      "dependencies": [],
      "executor_report": null,
      "verifier_verdict": null,
      "error_count": 0,
      "error_fingerprints": [],
      "discovered": false
    }
  ]
}
```

### Task Fields

- **passes**: `true` when verifier approves with evidence
- **dependencies**: Task IDs that must pass before this task is eligible
- **error_fingerprints**: Structured error identity for 3-strike detection (see below)
- **discovered**: `true` for tasks added during execution (dynamic task discovery)
- **executor_report**: Last executor output (status, changes, self-verification, issues)
- **verifier_verdict**: Last verifier output (verdict, evidence table, criteria table)

### Task Atomicity Rule

Each task MUST be one atomic unit of work:
- Touches a bounded set of files
- Has testable acceptance criteria
- Can be independently verified
- Multi-part tasks are split during plan parsing

## Cancel Signal (inside ralph-state.json)

Cancel signals are stored inside `ralph-state.json`, not a separate file. The following fields are set when cancellation is requested:

```json
{
  "cancel_requested": true,
  "cancel_reason": "user request",
  "cancel_at": "2024-..."
}
```

- **cancel_requested**: `true` when cancellation has been requested
- **cancel_reason**: reason string (e.g. `"user request"`, `"circuit-breaker"`, `"context-limit"`)
- **cancel_at**: ISO timestamp when cancel was requested

Check cancel status via `omh_state(action="cancel_check", mode="ralph")` — returns `{cancelled, reason, requested_at}`.

The cancel signal expires after `cancel_ttl_seconds` (default 30s) and is auto-cleared. Checked at the START of each invocation; stale signals are ignored (prevents orphaned cancel signals from blocking future runs).

## Error Fingerprinting

```json
{
  "task_id": "T-001",
  "iteration": 5,
  "category": "build|test|lint|runtime|timeout|unknown",
  "error_key": "TS2345",
  "raw_error": "error TS2345: Argument of type 'string' is not assignable...",
  "timestamp": "2026-04-07T06:45:00Z"
}
```

### Matching Rules

Two fingerprints match if ALL of:
1. Same `task_id` (errors on different tasks never match)
2. Same `category`
3. Same `error_key`

### Error Key Construction

1. Strip timestamps, absolute paths, line numbers, PIDs
2. Extract error type/code (e.g., `TS2345`, `ENOENT`, `AssertionError`)
3. If an error code exists → that IS the key
4. If no error code → first 200 chars of normalized message

### 3-Strike Behavior

When 3 matching fingerprints accumulate for a task:
1. Set task to blocked (NOT the whole plan)
2. Record the pattern and all 3 attempt summaries
3. Skip to next eligible task
4. If ALL remaining tasks are blocked → set `active=false`, `phase="blocked"`
