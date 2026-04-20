---
version: "1.0"
status: draft
created: "{timestamp}"
interview_id: "{interview_id}"
project_name: "{project_name}"
type: greenfield|brownfield
coverage:
  goal: HIGH|MEDIUM|LOW|CLEAR
  constraints: HIGH|MEDIUM|LOW|CLEAR
  success_criteria: HIGH|MEDIUM|LOW|CLEAR
  existing_context: HIGH|MEDIUM|LOW|CLEAR|N/A
rounds_completed: 0
---

# {project_name} — Requirements Specification

## Goal

What we are building and why. One to three paragraphs describing the desired outcome,
the problem being solved, and who benefits.

## Constraints

Technical, time, resource, regulatory, and compatibility constraints that bound
the solution space. Each constraint should be specific and actionable.

- **Technical**: {e.g., must run on Python 3.11+, must work offline}
- **Resources**: {e.g., single developer, no budget for paid APIs}
- **Compatibility**: {e.g., must integrate with existing auth system}
- **Timeline**: {e.g., MVP needed by end of week}
- **Regulatory**: {e.g., must handle PII per GDPR}

## Success Criteria

How we know this is done and working. Each criterion must be testable — if you
can't write a test or verification step for it, it's not a criterion.

1. {Specific, testable criterion}
2. {Specific, testable criterion}
3. {Specific, testable criterion}

## Existing Context

_Only present for brownfield projects._

The existing system, codebase, or infrastructure this work integrates with.
Include: relevant file paths, APIs, data models, and known technical debt
that affects the work.

## Assumptions

Things we are taking for granted. Each should be validated before or during
implementation. If an assumption turns out to be wrong, the plan may need revision.

- {Assumption 1}
- {Assumption 2}

## Open Questions

Things that still need answers. Each includes which dimension it affects and
why it matters. These should be addressed during planning (ralplan) or early
in implementation.

- {Question 1} — affects: {dimension}, impact: {what breaks if unanswered}
- {Question 2} — affects: {dimension}, impact: {what breaks if unanswered}
