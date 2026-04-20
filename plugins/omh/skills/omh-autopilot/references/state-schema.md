# Autopilot State Schema

State file: `.omh/state/autopilot-state.json`

## Schema

```json
{
  "session_id": "uuid",
  "started_at": "ISO-8601",
  "last_updated_at": "ISO-8601",
  "goal": "Original user goal/input",
  "phase": "requirements|planning|execution|qa|validation|cleanup|complete|blocked|paused",
  "phase_step": "description of current sub-step",
  "context_checkpoint": false,
  "spec_file": null,
  "plan_file": null,
  "ralph_state_path": ".omh/state/ralph-state.json",
  "ralph_iteration": 0,
  "qa_cycle": 0,
  "max_qa_cycles": 5,
  "qa_error_history": [],
  "validation_round": 0,
  "max_validation_rounds": 3,
  "validation_verdicts": {},
  "evidence_summary": "",
  "skip_qa": false,
  "skip_validation": false,
  "pause_after_phase": null
}
```

## Field Definitions

- **phase**: Current pipeline phase. Drives dispatch logic.
- **phase_step**: Human-readable sub-step (e.g., "ralph iteration 5", "QA cycle 2 fix")
- **context_checkpoint**: When `true`, next invocation MUST be a fresh session. Set at phase boundaries (2→3, 3→4). Cleared on read.
- **spec_file**: Path to confirmed spec (set after Phase 0)
- **plan_file**: Path to consensus plan (set after Phase 1)
- **ralph_iteration**: Count of ralph iterations completed in Phase 2
- **qa_cycle**: Current QA cycle number (1-indexed, Phase 3)
- **qa_error_history**: Error fingerprints from QA failures, for 3-strike detection
- **validation_verdicts**: Map of reviewer role → verdict. All must be APPROVE to advance.
- **evidence_summary**: Truncated build/test output (last 2000 chars). For inter-session continuity, not primary diagnostics — each fresh session re-runs commands.
- **skip_qa / skip_validation**: Optional flags to skip phases
- **pause_after_phase**: If set (e.g., "planning"), autopilot pauses after that phase for user review

## Phase Transitions

```
requirements → planning → execution → qa → validation → cleanup → complete
                                        ↑ checkpoint    ↑ checkpoint
```

Phase boundaries 2→3 and 3→4 set `context_checkpoint: true`.

## Dispatch Priority (Fresh Start)

When no autopilot-state.json exists, check artifacts in order:

1. `.omh/specs/*-spec.md` with `status: confirmed` → skip to Phase 1 (planning)
2. `.omh/plans/ralplan-*.md` → skip to Phase 2 (execution)
3. `.omh/state/ralph-state.json` with `phase: "complete"` → skip to Phase 3 (QA)
4. Nothing → start at Phase 0 (requirements)
