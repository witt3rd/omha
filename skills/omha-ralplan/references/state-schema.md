# OMHA State Schema

All OMHA skills write state to `.omha/` in the project directory. This enables resumability across context resets and session interruptions.

## Directory Structure

```
.omha/
├── state/
│   ├── ralplan-state.json      # Active ralplan session
│   ├── ralph-state.json        # Active ralph loop
│   ├── autopilot-state.json    # Active autopilot pipeline
│   └── interview-state.json    # Active deep-interview session
├── plans/
│   └── ralplan-{timestamp}.md  # Consensus plans
├── specs/
│   └── interview-{timestamp}.md # Deep-interview specifications
└── logs/
    └── {skill}-{timestamp}.log # Audit trail
```

## State File Conventions

- All state files are JSON
- Every state file has: `goal`, `phase`, `started_at`, `updated_at`
- Skills check for existing state on invocation and offer to resume
- State is deleted on successful completion (clean exit)
- State is preserved on interruption (enables resume)

## Common Fields

```json
{
  "goal": "Human-readable goal description",
  "phase": "current phase name",
  "started_at": "ISO 8601 timestamp",
  "updated_at": "ISO 8601 timestamp",
  "round": 1,
  "status": "active|complete|failed|interrupted"
}
```
