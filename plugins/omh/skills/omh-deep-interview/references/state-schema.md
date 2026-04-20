# Deep Interview State Schema

State file: `.omh/state/interview-{id}.json`

Only one active interview at a time. If an active state file exists when the skill
is invoked, offer to resume or abandon it.

## Schema

```json
{
  "interview_id": "di-20260407-abc123",
  "project_name": "my-project",
  "goal_summary": "Brief user-provided project description from opening",
  "type": "greenfield|brownfield",
  "current_round": 0,
  "max_rounds": 5,
  "status": "active|paused|confirmed|abandoned",
  "started_at": "2026-04-07T06:30:00Z",
  "updated_at": "2026-04-07T06:35:00Z",
  "coverage": {
    "goal": "HIGH",
    "constraints": "HIGH",
    "success_criteria": "HIGH",
    "existing_context": "HIGH|N/A"
  },
  "rounds": [
    {
      "round": 1,
      "dimension_focus": "goal",
      "summary": "Asked about primary objective. User explained they want a CLI tool for X. Clarified it's for personal use, not a team tool.",
      "coverage_after": {
        "goal": "MEDIUM",
        "constraints": "HIGH",
        "success_criteria": "HIGH",
        "existing_context": "N/A"
      }
    }
  ],
  "spec_file": null
}
```

## Field Definitions

- **interview_id**: Unique ID, format `di-{YYYYMMDD}-{short_random}`
- **project_name**: User-provided name, used in spec filename
- **type**: `greenfield` (3 dimensions) or `brownfield` (4 dimensions)
- **current_round**: 0 = opening complete, 1+ = interview rounds
- **max_rounds**: Default 5, extensible to 10 if user requests
- **status**: `active` (in progress), `paused` (interrupted), `confirmed` (spec accepted), `abandoned` (user cancelled)
- **coverage**: Coarse bins per dimension. `N/A` for existing_context on greenfield projects
- **rounds**: Array of round summaries. Each summary max ~200 words. NOT full transcripts.
- **spec_file**: Path to generated spec, null until spec generation

## Coverage Bins

- **HIGH**: Dimension barely explored. No clear answers yet.
- **MEDIUM**: Some information gathered but significant gaps remain.
- **LOW**: Mostly clear with a few minor gaps.
- **CLEAR**: Well-defined. Further questioning unlikely to add value.
- **N/A**: Dimension not applicable (existing_context on greenfield).

## Lifecycle

```
invoke skill
  → check for existing active state
    → found: offer resume/abandon
    → not found: create new state (opening phase)
  → interview loop (rounds 1-5+)
    → update state after each round
  → user says "enough" or round 5 reached
    → generate draft spec
    → user confirms/edits/abandons
      → confirmed: status=confirmed, spec_file set, state kept for audit
      → abandoned: status=abandoned, spec deleted
```
