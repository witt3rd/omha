---
name: omha-ralplan
description: >
  Consensus planning via multi-agent debate. Three perspectives (Planner, Architect, Critic)
  iterate until consensus or max rounds. Produces a vetted implementation plan. Use for any
  non-trivial task where a single perspective might miss blind spots.
version: 0.1.0
tags: [planning, multi-agent, consensus, architecture]
category: omha
metadata:
  hermes:
    requires_toolsets: [terminal]
---

# OMHA Ralplan — Consensus Planning

## When to Use

- Before implementing any feature that touches multiple files or components
- When architectural decisions need validation from multiple perspectives
- When you need a plan that's been stress-tested against adversarial critique
- When the user says: "plan this", "consensus plan", "ralplan", "let's think this through"

## When NOT to Use

- Trivial single-file changes (just do them)
- Tasks where the approach is obvious and low-risk
- When the user explicitly wants to skip planning

## Prerequisites

- A clear goal or specification (if ambiguous, use `omha-deep-interview` first)
- The `delegate_task` tool must be available

## Procedure

### Phase 0: Context Gathering

Before planning, gather project context:
1. Read relevant files to understand the codebase structure
2. Identify existing patterns, conventions, and constraints
3. Summarize context into a brief (~500 words) that all agents will receive

### Phase 1: Planning Loop (max 3 rounds)

Each round proceeds sequentially:

**Step 1 — Planner**
Delegate to a subagent with the Planner role prompt (load from `references/role-planner.md`):
```
delegate_task(
    goal="Create an implementation plan for: {goal}",
    context="{role_prompt}\n\n{project_context}\n\n{previous_feedback if any}"
)
```

**Step 2 — Architect Review**
Delegate to a subagent with the Architect role prompt (load from `references/role-architect.md`):
```
delegate_task(
    goal="Review this implementation plan for architectural soundness",
    context="{role_prompt}\n\n{project_context}\n\nPLAN TO REVIEW:\n{planner_output}"
)
```

**Step 3 — Critic Challenge**
Delegate to a subagent with the Critic role prompt (load from `references/role-critic.md`):
```
delegate_task(
    goal="Critically challenge this plan and architect review",
    context="{role_prompt}\n\n{project_context}\n\nPLAN:\n{planner_output}\n\nARCHITECT REVIEW:\n{architect_output}"
)
```

**Step 4 — Consensus Check**
Check all three verdicts:
- If ALL three are APPROVE → consensus reached, proceed to output
- If any is REJECT or REQUEST_CHANGES → incorporate feedback, loop back to Step 1
- If round 3 and no consensus → output the best plan with unresolved concerns noted

### Phase 2: Output

Write the consensus plan to `.omha/plans/ralplan-{timestamp}.md` containing:
1. The final plan (from Planner)
2. Architect approval notes
3. Critic approval notes (or unresolved concerns)
4. Round count and consensus status

Also write a summary to the user.

## State Management

State is tracked in `.omha/state/ralplan-state.json`:
```json
{
  "goal": "...",
  "round": 1,
  "phase": "planner|architect|critic|complete",
  "consensus": false,
  "plan_file": ".omha/plans/ralplan-{timestamp}.md"
}
```

If a ralplan session is interrupted, check for existing state and resume from the last completed phase.

## Deliberate Mode (--deliberate)

When the user requests deliberate mode or uses "deliberate", "ADR", or "decision record", the Architect's output should follow Architecture Decision Record (ADR) format. Load `references/adr-template.md` for the template.

## Pitfalls

- Don't let the loop run more than 3 rounds — if no consensus by round 3, output with caveats
- Each subagent must receive the project context, not just the plan — they need to evaluate against reality
- The Critic should challenge, not block — if issues are minor, APPROVE with reservations
- If the goal is ambiguous, stop and suggest `omha-deep-interview` instead of planning with unclear requirements
