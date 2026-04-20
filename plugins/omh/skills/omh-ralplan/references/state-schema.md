# OMH Ralplan — State Schema

Documents the state files written and read by the `omh-ralplan` skill.

## State File: `.omh/state/ralplan-state.json`

Written via `omh_state(action="write", mode="ralplan", data={...})`.

```json
{
  "goal": "Human-readable planning goal",
  "phase": "planner|architect|critic|complete|blocked",
  "round": 1,
  "max_rounds": 3,
  "consensus": false,
  "plan_file": ".omh/plans/ralplan-<slug>.md",
  "started_at": "ISO 8601 timestamp",
  "updated_at": "ISO 8601 timestamp"
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | The planning goal passed in by the user or caller |
| `phase` | string | Current phase: `planner`, `architect`, `critic`, `complete`, `blocked` |
| `round` | integer | Current debate round (starts at 1, max `max_rounds`) |
| `max_rounds` | integer | Maximum rounds before `blocked` (default: 3) |
| `consensus` | boolean | Whether all three agents agreed in the current round |
| `plan_file` | string | Path to the consensus plan file once `phase="complete"` |
| `started_at` | string | ISO 8601 timestamp when this session started |
| `updated_at` | string | ISO 8601 timestamp of last write |

## Plan File: `.omh/plans/ralplan-<slug>.md`

The consensus plan produced when all three agents agree. The `<slug>` is derived
from the goal (e.g., "implement auth module" → `ralplan-implement-auth-module.md`).

Plan files are **preserved** after the session ends (not deleted with state).
They are the handoff artifact consumed by `omh-ralph` and `omh-autopilot`.

## State Lifecycle

```
phase: "planner"   → Planner agent drafts initial plan
phase: "architect" → Architect reviews and proposes changes
phase: "critic"    → Critic challenges assumptions
                     If disagreement: round++ and restart from "planner"
                     If consensus: phase="complete"
phase: "complete"  → Consensus reached; plan_file is set and written
phase: "blocked"   → max_rounds exceeded with no consensus; needs human input
```
