---
name: omh-deep-interview
description: Socratic reqs interview; clarify vague/ambiguous goals
version: 2.0.0
metadata:
  hermes:
    tags: [interview, requirements, socratic, ambiguity, specification]
    category: omh
    requires_toolsets: [terminal, omh]
---

# OMH Deep Interview — Requirements Specification Through Conversation

## When to Use

- The goal is vague, underspecified, or could be interpreted multiple ways
- Before planning (omh-ralplan) or implementation on non-trivial work
- The user says: "deep interview", "requirements", "what should we build", "help me think through this"
- omh-ralplan determines the goal is too ambiguous to plan
- You're unsure what the user actually wants
- **Domain unfamiliarity:** if the goal requires external knowledge of an unfamiliar domain, suggest running `omh-deep-research` first to gather context, then resume the interview with the confirmed report as input.

## When NOT to Use

- The goal is already crystal clear and bounded
- A confirmed spec already exists in `.omh/specs/` for this project
- The user explicitly wants to skip requirements gathering
- Trivial single-file changes where the task is obvious

## Prerequisites

- Conversational access to the user (this skill asks questions and needs answers)
- Write access to `.omh/` directory for state and spec files

## Procedure

Follow these phases in order. The skill operates through conversation with the user
and file writes for state and spec output.

### Phase 0: Check for Existing State

Before starting a new interview:

1. Enumerate active interviews:
   ```
   listed = omh_state(action="list_instances", mode="interview")
   ```
   Each entry carries `instance_id` (the interview id) and `active` flag.
   If `omh_state` is unavailable, glob `.omh/state/interview--*.json` manually.
2. If any active interview exists, tell the user: "There's an active interview for '{project_name}' (id={id}). Resume, start fresh, or abandon it?"
3. If resuming: `omh_state(action="read", mode="interview", instance_id="{id}")` — read round summaries to reconstruct context
4. If abandoning: `omh_state(action="write", mode="interview", instance_id="{id}", data={...status: "abandoned"})`, then proceed to Phase 1 with a NEW id
5. If no active state found: proceed to Phase 1
6. Concurrent interviews on different projects are permitted; do not block.
6. **Check for existing research context (omh-deep-research sentinel):**
   if any `.omh/research/*-report.md` exists with frontmatter
   `status: confirmed`, mention it to the user as available context for
   the interview (e.g., "I see a confirmed research report on '{topic}'
   at `{path}` — want me to fold that in as background?"). Do NOT
   auto-load it; the user decides.

### Phase 1: Opening

Start the interview with two questions:

1. **Project description**: "Describe what you want to build in 2-3 sentences. What's the core idea?"
2. **Greenfield or brownfield**: "Is this a new project from scratch, or are you working within an existing codebase or system?"

Then:
- Generate an interview ID: `di-{YYYYMMDD}-{short_random}` (e.g., `di-20260407-x7k`)
- Ask the user for a short project name (for filenames)
- Create the state file at `.omh/state/interview--{id}.json` (engine derives this from `instance_id="{id}"`) with:
  - All coverage dimensions set to `HIGH`
  - `type` set to `greenfield` or `brownfield` based on user's answer
  - `existing_context` coverage set to `N/A` for greenfield projects
  - Round 0 summary capturing the opening answers
- Tell the user: "Got it. I'll ask up to 5 rounds of questions to clarify requirements. You can say 'enough' at any point if you feel we've covered what's needed."

### Phase 2: Interview Loop

Run up to 5 rounds (extensible to 10 if user requests). Each round:

**Step 1 — Select dimension to probe**

Compare coverage bins across dimensions. Target the dimension with the highest ambiguity.
When multiple dimensions share the same bin, use weights to break ties:
- Greenfield: Goal (0.40) > Constraints (0.30) = Success Criteria (0.30)
- Brownfield: Goal (0.35) > Constraints (0.25) = Success Criteria (0.25) > Existing Context (0.15)

Load `references/scoring-rubric.md` for detailed bin definitions and examples.

**Step 2 — Ask the question**

Ask ONE primary question targeting the selected dimension. Make it specific and
grounded in what the user has already told you. Don't ask generic questions — reference
their earlier answers.

Good: "You mentioned this is a CLI tool for personal use. What happens when you run it with no tasks configured — should it create a default list, show an error, or something else?"

Bad: "What are your constraints?"

Allow 1-2 brief follow-ups if the user's answer is unclear, contradictory, or raises
new questions. Don't force follow-ups if the answer is clear.

**Step 3 — Adaptive questioning (if stuck)**

If a dimension has been targeted for 2 or more consecutive rounds without moving from
its current bin, change your approach:
- Try asking from a completely different angle
- Propose a concrete example and ask "Is this right, or what would you change?"
- Ask what's blocking clarity: "What makes this hard to pin down?"
- Ask the user to define a specific term they've been using ambiguously

**Step 4 — Update coverage**

After processing the user's answer, re-assess the coverage bin for the targeted dimension.
Use the rubric in `references/scoring-rubric.md`. Be conservative — when in doubt, keep
the bin at its current level rather than prematurely lowering it.

**Step 5 — Update state**

Update the interview state (increment round, add summary, update coverage):
```
omh_state(action="write", mode="interview", instance_id="{id}", data={...updated state with new round...})
```
Each round summary: max ~200 words — capture what was learned, not the full exchange.

**Step 6 — Present coverage and ask to continue**

Show the user where things stand:

```
Coverage after round {N}:
  Goal:             [MEDIUM]  →  Some clarity, but scope needs bounding
  Constraints:      [LOW]     →  Mostly clear, data format TBD
  Success Criteria: [HIGH]    →  Need testable criteria
  Existing Context: [N/A]     →  Greenfield project
```

Then ask: **"Want to continue refining, or is this enough to work with?"**

- If the user says continue: proceed to next round
- If the user says enough/done/that's it: proceed to Phase 3
- If round 5 reached: "We've done 5 rounds. Want to continue (up to 10 more), or shall I generate the spec from what we have?"
- If round 10 reached: proceed to Phase 3 automatically

**The user always controls exit. Never auto-terminate based on coverage scores.**

### Phase 3: Spec Generation

When the user confirms exit (or max rounds reached):

1. Load `templates/spec-template.md`
2. Synthesize a specification from the accumulated round summaries in the state file
3. Fill in every section of the template:
   - **Goal**: Synthesize from rounds that targeted the goal dimension
   - **Constraints**: Synthesize from constraint-focused rounds
   - **Success Criteria**: Must be specific and testable — if a criterion can't be verified, flag it in Open Questions instead
   - **Existing Context**: Only for brownfield; synthesize from context-focused rounds
   - **Assumptions**: Things the user stated or implied that haven't been validated
   - **Open Questions**: Anything with coverage still at HIGH or MEDIUM — these are unresolved
4. Set YAML frontmatter:
   - `status: draft`
   - `coverage`: current bin values
   - `rounds_completed`: total rounds done
5. Write to `.omh/specs/{project-name}-spec.md`
6. Update state: `spec_file` = path to spec

### Phase 4: Confirmation

Display the full draft spec to the user and ask:

**"Here's the specification I've drafted. Please review it. You can:**
- **Confirm** — I'll finalize it and downstream skills (ralplan, autopilot) will use it
- **Request changes** — Tell me what to adjust, and I'll ask follow-up questions
- **Abandon** — Discard the spec and interview"

Handle each response:

**On confirm**:
- Update spec frontmatter: `status: confirmed`
- Update state: `status: confirmed`
- Tell the user: "Spec confirmed and saved to {path}. You can now use `omh-ralplan` to create an implementation plan from this spec."

**On request changes**:
- Ask targeted follow-up questions about the specific sections the user wants changed
- Regenerate the spec
- Return to the confirmation prompt

**On abandon**:
- Delete the spec file
- Update state: `status: abandoned`
- Tell the user the interview has been discarded

**Only specs with `status: confirmed` are considered valid by downstream skills.**

### Phase 5: Logging

Throughout the interview, write structured events to `.omh/logs/interview-{id}.log`:

```
2026-04-07T06:30:00Z STARTED interview_id=di-20260407-x7k project=my-project type=greenfield
2026-04-07T06:31:15Z ROUND round=1 dimension=goal coverage_change=goal:HIGH→MEDIUM
2026-04-07T06:33:42Z ROUND round=2 dimension=constraints coverage_change=constraints:HIGH→LOW
2026-04-07T06:35:00Z USER_EXIT round=3 reason=user_confirmed
2026-04-07T06:35:30Z SPEC_GENERATED path=.omh/specs/my-project-spec.md status=draft
2026-04-07T06:36:00Z SPEC_CONFIRMED path=.omh/specs/my-project-spec.md
```

Log events and decisions only — NOT conversation content.

## Sentinel Convention

Downstream skills detect completed interviews by checking for files matching
`.omh/specs/*-spec.md` with `status: confirmed` in the YAML frontmatter.

- **omh-ralplan**: If a confirmed spec exists, use it as the goal/specification input
  to the Planner subagent instead of asking the user to describe the goal.
- **omh-autopilot**: If a confirmed spec exists, skip Phase 0 (requirements) entirely.

## State Management

State file: `.omh/state/interview--{id}.json` (engine path; pass `instance_id="{id}"` to `omh_state`)

See `references/state-schema.md` for the full schema.

Key rules:
- Each interview is a separate instance keyed by its id; concurrent interviews on different projects are permitted
- State stores round summaries (max ~200 words each), NOT full transcripts
- State is preserved after completion (for audit trail)
- Resumability is inherently lossy — round summaries help reconstruct context but lose nuance from the original conversation

## Pitfalls

- **Never auto-terminate based on scores.** Coverage bins are advisory heuristics for question targeting. The user always decides when they're done.
- **Don't store full transcripts.** Round summaries keep state compact and respect context window limits on resume. Accept that resumability is approximate, not exact.
- **Ask about brownfield, don't auto-detect.** Checking for package.json etc. is unreliable and presumptuous. Let the user tell you.
- **One active interview *per project*.** Use a fresh `instance_id` per interview. If an active interview already exists for the same project, offer to resume or abandon it before starting a parallel one with the same id.
- **Spec must be confirmed.** Draft specs are not valid input for downstream skills. The user must explicitly confirm.
- **Don't ask generic questions.** Reference the user's earlier answers. "What are your constraints?" is lazy. "You mentioned this is for personal use on Linux — are there other platforms it needs to work on?" is useful.
- **Be conservative with coverage assessment.** When in doubt, keep the bin at its current level. It's better to ask one more question than to prematurely declare a dimension CLEAR.
