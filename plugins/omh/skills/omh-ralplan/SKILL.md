---
name: omh-ralplan
description: >
  Consensus planning via multi-agent debate. Three perspectives (Planner, Architect, Critic)
  iterate until consensus or max rounds. Produces a vetted implementation plan. Use for any
  non-trivial task where a single perspective might miss blind spots.
version: 2.0.0
tags: [planning, multi-agent, consensus, architecture]
category: omh
metadata:
  hermes:
    requires_toolsets: [terminal, omh]
---

# OMH Ralplan — Consensus Planning

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

- A clear goal or specification (if ambiguous, use `omh-deep-interview` first)
- The `delegate_task` tool must be available

## Procedure

### Phase 0: Context Gathering

Before planning, gather project context:
1. Read relevant files to understand the codebase structure
2. Identify existing patterns, conventions, and constraints
3. Summarize context into a brief (~500 words) that all agents will receive

### Phase 1: Planning Loop (max 3 rounds)

**Round 1 — All Sequential** (Planner → Architect → Critic):

**Step 1 — Planner** (single delegate_task)
```
delegate_task(
    goal="[omh-role:planner] Create an implementation plan for: {goal}\n\n{detailed_requirements}",
    context="# Project Context\n\n{project_context}"
)
```
The goal should include the full specification — don't assume the subagent knows anything.

**Step 2 — Architect Review** (single delegate_task)
```
delegate_task(
    goal="[omh-role:architect] Review this implementation plan for architectural soundness:\n\nPLAN:\n{planner_output}",
    context="# Project Context\n\n{project_context}"
)
```

**Step 3 — Critic Challenge** (single delegate_task)
```
delegate_task(
    goal="[omh-role:critic] Critically challenge this plan and architect review:\n\nPLAN SUMMARY:\n{plan_summary}\n\nARCHITECT REVIEW:\n{architect_verdict_and_concerns}",
    context="# Project Context\n\n{project_context}"
)
```

**Step 4 — Consensus Check**
Check all three verdicts:
- If ALL three are APPROVE → consensus reached, proceed to output
- If any is REQUEST_CHANGES → collect all feedback, proceed to Round 2
- If any is REJECT → output concerns and ask user whether to continue

**Round 2+ — Planner Revises, Architect + Critic Re-review in Parallel**:

When looping, the Planner must receive ALL feedback (Architect concerns + Critic critical issues + warnings). Be explicit about what needs to change — include the specific concern IDs (A1, C1, W1, etc.).

For Round 2 re-reviews, Architect and Critic are independent — run them in parallel via batch delegate_task:
```
delegate_task(tasks=[
    {goal: "[omh-role:architect] Re-review revised plan:\n{revised_plan}\n\nPrior concerns: {architect_concerns}", context: "{project_context}"},
    {goal: "[omh-role:critic] Re-review revised plan:\n{revised_plan}\n\nPrior concerns: {critic_concerns}", context: "{project_context}"}
])
```
This saves significant time (Round 2 re-reviews ran 14 seconds parallel vs ~120 seconds sequential).

### Phase 2: Output

Write the consensus plan to `.omh/plans/ralplan-{slug}.md` containing:
1. Consensus status (rounds, verdicts per round)
2. Revision summary (what changed from feedback)
3. The final plan (tasks with dependencies, complexity, acceptance criteria)
4. Risks and open questions
5. Round count and consensus status

Use a descriptive slug, not a timestamp: `ralplan-deep-interview-consensus.md` not `ralplan-20260407.md`.

Also write a summary to the user with the key design decisions that emerged from the debate.

## State Management

If the `omh` plugin is available, use it for state:
```
omh_state(action="write", mode="ralplan", data={
    "goal": "...", "round": 1,
    "phase": "planner|architect|critic|complete",
    "consensus": false, "plan_file": ".omh/plans/ralplan-{slug}.md"
})
```

If the plugin is not available, write `.omh/state/ralplan-state.json` manually.

If a ralplan session is interrupted, check for existing state and resume from the last completed phase:
```
state = omh_state(action="read", mode="ralplan")
```

## Deliberate Mode (--deliberate)

When the user requests deliberate mode or uses "deliberate", "ADR", or "decision record", the Architect's output should follow Architecture Decision Record (ADR) format. Load `references/adr-template.md` for the template.

## Pitfalls

- **Use `[omh-role:NAME]` markers in the goal field** — the OMH plugin automatically injects the role prompt into the subagent's system prompt. Never inline role prompt text manually. Available roles: planner, architect, critic, executor, verifier, analyst, security-reviewer, code-reviewer, test-engineer, debugger. Fallback without plugin: `omh_state(action="load_role", role="NAME")` and pass returned prompt in context.
- **Include full specifications in the goal** — subagents start with zero context. The goal + context must be self-contained.
- **Run Round 2+ reviews in parallel** — Architect and Critic are independent in re-review rounds. Use batch delegate_task to save time.
- **Summarize feedback with IDs for the Planner** — when looping, label feedback as A1/A2/C1/C2/W1 etc. so the Planner can address each point explicitly and the reviewers can check each one off.
- Don't let the loop run more than 3 rounds — if no consensus by round 3, output with caveats
- Each subagent must receive the project context, not just the plan — they need to evaluate against reality
- The Critic should challenge, not block — if issues are minor, APPROVE with reservations
- If the goal is ambiguous, stop and suggest `omh-deep-interview` instead of planning with unclear requirements
- **Use todo tracking** — update a todo list with round/phase status so the user sees progress during what can be a 5-10 minute process
- **When porting/adapting from a reference system, feed actual source to subagents** — if designing a skill inspired by another system (e.g., OMC → Hermes), the Planner, Architect, and Critic must read the actual source implementation, not just briefs or summaries. Extract reference docs from the source repo first, pass file paths in the delegate_task goal so subagents read them. Summaries lose critical field names, state schemas, edge cases, and design patterns.
- **The Critic's simplicity test can change architecture** — don't dismiss it. In the ralph consensus, the Critic proposed one-task-per-invocation (instead of an in-session loop) which both reviewers then approved as fundamentally better. The consensus process finds the right architecture, not just validates the proposed one.
