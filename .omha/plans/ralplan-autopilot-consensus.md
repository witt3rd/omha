# OMHA Autopilot — Implementation Plan (v2)

## Summary

omha-autopilot is a **composition skill** that orchestrates omha-deep-interview, omha-ralplan, and omha-ralph into a 6-phase autonomous pipeline (Requirements → Planning → Execution → QA → Validation → Cleanup).

**Core design principle: one-phase-step-per-invocation.** Each autopilot invocation reads `autopilot-state.json`, performs ONE unit of work (a single ralph iteration, one QA cycle, one validation round, etc.), updates state, and exits. The caller — user, cron job, or wrapper script — re-invokes autopilot until state reaches `phase: "complete"`. This is the same pattern ralph uses (one task per invocation), applied one level up.

**Why not loop in-session?** Ralph was designed for fresh context per invocation. Running ralph's full procedure (skill_view + delegate executor + gather evidence + delegate verifier + update state) consumes 5-12K tokens per iteration. A 15-task plan would accumulate 80-180K tokens in a single session, exhausting context before QA/Validation phases ever run. The multi-session design preserves ralph's fresh-context property at every level.

**Why not delegate ralph iterations as subagents?** Hermes enforces MAX_DEPTH = 2 with no recursive delegation. Autopilot runs at depth 1. Ralph needs to delegate to executor/verifier subagents at depth 2. If autopilot delegated ralph as a subagent (depth 2), ralph's executor/verifier calls would require depth 3 — blocked by Hermes.

**Invocation pattern:**
```
Invocation 1:  read state → Phase 0 (requirements) → update state → EXIT
Invocation 2:  read state → Phase 1 (planning) → update state → EXIT
Invocation 3:  read state → Phase 2, ralph iteration 1 → update state → EXIT
Invocation 4:  read state → Phase 2, ralph iteration 2 → update state → EXIT
...
Invocation N:  read state → Phase 2, ralph complete → update state → EXIT
Invocation N+1: read state → Phase 3, QA cycle 1 → update state → EXIT  [FRESH SESSION]
...
Invocation M:  read state → Phase 4, validation round 1 → update state → EXIT  [FRESH SESSION]
...
Final:         read state → Phase 5 (cleanup) → delete state → EXIT
```

Phase boundaries (2→3, 3→4) are mandatory fresh-session checkpoints. Within Phase 2, each ralph iteration is also a separate invocation, getting fresh context automatically.

The skill does not reimplement any component — it detects existing artifacts (.omha/specs/, .omha/plans/, .omha/state/) to skip completed phases, and adds two phases that don't exist in the components: QA cycling (Phase 3) and multi-reviewer validation (Phase 4).

---

## Tasks

### Task 1: Define autopilot-state.json Schema

**Description**: Design the state file schema for `.omha/state/autopilot-state.json`. This is the central persistence mechanism that enables multi-session operation. Must track enough state for any invocation to determine exactly what to do next.

**Dependencies**: None

**Complexity**: Medium (elevated from Low — schema now drives multi-session behavior)

**Acceptance Criteria**:
- Schema documented in `omha-autopilot/references/state-schema.md`
- Required fields:
  - `session_id` (UUID, generated on fresh start)
  - `started_at`, `last_updated_at` (ISO timestamps)
  - `phase`: one of `requirements`, `planning`, `execution`, `qa`, `validation`, `cleanup`, `complete`, `blocked`
  - `phase_step`: sub-phase progress indicator (e.g., "ralph_iteration" during execution, "qa_cycle" during QA)
  - `ralph_iteration`: integer count of ralph invocations completed in Phase 2
  - `context_checkpoint`: boolean flag — when true, the NEXT invocation MUST be in a fresh session (set at phase boundaries)
  - `spec_file`: path to confirmed spec (set after Phase 0)
  - `plan_file`: path to consensus plan (set after Phase 1)
  - `ralph_state_path`: path to ralph-state.json (set during Phase 2)
  - `qa_cycle`: current QA cycle number (Phase 3)
  - `max_qa_cycles`: default 5
  - `qa_error_history[]`: fingerprints of QA failures for 3-strike detection
  - `validation_round`: current validation round (Phase 4)
  - `max_validation_rounds`: default 3
  - `validation_verdicts{}`: keyed by reviewer role (architect/security/code-reviewer), value is APPROVE or REQUEST_CHANGES with details
  - `evidence_summary`: truncated last build/test output (max 2000 chars) for state continuity
- Schema explicitly documents which fields trigger which behavior on read
- Example state file for each phase included in schema doc

---

### Task 2: Implement Phase 0 — Requirements (Deep Interview Detection/Invocation)

**Description**: Write the Phase 0 section of SKILL.md. This phase is **potentially interactive** and must be documented honestly. On invocation, check for existing confirmed specs. If found, skip. If not found, the behavior depends on input concreteness.

**Dependencies**: Task 1 (state schema)

**Complexity**: Medium

**Acceptance Criteria**:
- Detects existing confirmed specs via glob + YAML frontmatter `status: confirmed`
- Vagueness heuristic documented (concrete = contains file paths, function names, specific technology choices, quantified requirements; vague = abstract goals, no technical anchors)
- For vague input: **honestly documents that this phase is interactive**. The agent loads omha-deep-interview and follows it. The user must participate. Alternatively, the user can run deep-interview separately before invoking autopilot.
- For concrete input: generates an inline spec at `.omha/specs/{slug}-spec.md` with `status: confirmed`
- State updated: `phase: "planning"`, `spec_file` set
- **Phase 0 exits after completion** — next invocation picks up at Phase 1
- Documents clearly: "If you want fully autonomous execution, run deep-interview separately first, then invoke autopilot (which will detect the confirmed spec and skip Phase 0)"

---

### Task 3: Implement Phase 1 — Planning (Ralplan Detection/Invocation)

**Description**: Write Phase 1. Check for existing consensus plans. If found, skip. If not, invoke omha-ralplan. This is a single-invocation phase — ralplan runs once and produces a plan.

**Dependencies**: Task 1, Task 2

**Complexity**: Low

**Acceptance Criteria**:
- Detects existing ralplan output via glob `.omha/plans/ralplan-*.md` or `.omha/plans/consensus-*.md`
- When invoking ralplan: passes the spec file path as the goal source
- State updated: `phase: "execution"`, `plan_file` set, `ralph_iteration: 0`, `context_checkpoint: true`
- `context_checkpoint: true` ensures the transition to Phase 2 happens in a fresh session
- Skips cleanly when plan already exists

---

### Task 4: Implement Phase 2 — Execution (Ralph Iterations)

**Description**: Write Phase 2 — the critical ralph orchestration. **Each autopilot invocation during Phase 2 performs exactly ONE ralph iteration.** The autopilot skill instructs the agent to: load omha-ralph, follow ralph's procedure (which will pick one task, execute, verify, update state), then update autopilot state and exit. The caller re-invokes for the next iteration.

**Dependencies**: Task 1, Task 3

**Complexity**: High

**Acceptance Criteria**:
- Each invocation: load ralph skill → follow ralph procedure (one task) → check ralph-state.json → update autopilot-state.json → exit
- After each ralph iteration, autopilot reads ralph-state.json:
  - `phase: "execute"`, `active: true` → increment `ralph_iteration`, exit (caller re-invokes)
  - `phase: "complete"` → set autopilot `phase: "qa"`, `context_checkpoint: true`, exit
  - `phase: "blocked"` → set autopilot `phase: "blocked"`, report blockers, exit
- **Evidence truncation**: when recording `evidence_summary` in autopilot-state.json, cap build/test output at 2000 characters (last 2000 chars, which contain the most relevant failure info)
- Does NOT contain a loop — the single-iteration pattern is explicit
- Does NOT reimplement any ralph logic — refers to ralph's own procedure
- Does NOT estimate iteration counts — the number of iterations depends entirely on the plan

---

### Task 5: Implement Phase 3 — QA Cycling

**Description**: Write Phase 3 — post-ralph QA cycling. Each autopilot invocation during Phase 3 performs ONE QA cycle: run build+test+lint, check results, fix if needed, update state, exit. Phase 3 starts in a mandatory fresh session (context_checkpoint from Phase 2→3 transition).

**Dependencies**: Task 1, Task 4

**Complexity**: Medium

**Acceptance Criteria**:
- **Fresh session mandatory**: Phase 3 always starts in a new session (enforced by context_checkpoint)
- Each invocation: run build + test + lint → if all pass, advance to Phase 4 → if failures, diagnose and fix → update state → exit
- On failure: delegate diagnosis to architect subagent (read-only analysis), then delegate fix to executor subagent — this fits within depth limits since autopilot is the orchestrator
- Error fingerprinting for 3-strike detection (reuse ralph's fingerprint pattern from `qa_error_history[]`)
- Max 5 cycles tracked in `qa_cycle` state field
- Same error 3x → set `phase: "blocked"`, report the fundamental issue
- If all pass on first cycle: set `phase: "validation"`, `context_checkpoint: true`, exit
- **Evidence truncation**: build/test/lint output capped at 2000 chars in state

---

### Task 6: Implement Phase 4 — Multi-Reviewer Validation

**Description**: Write Phase 4 — parallel multi-perspective review. Each invocation performs ONE validation round. Phase 4 starts in a mandatory fresh session. Three parallel delegate_task calls for reviewers. On rejection: fix and exit (next invocation re-validates).

**Dependencies**: Task 1, Task 5

**Complexity**: Medium

**Acceptance Criteria**:
- **Fresh session mandatory**: Phase 4 always starts in a new session (enforced by context_checkpoint)
- Each invocation: gather fresh build/test evidence → delegate 3 parallel reviews → parse verdicts → fix or advance → exit
- Three parallel delegate_task calls (exactly 3 = Hermes concurrent subagent limit)
- Each reviewer receives: the original spec, the plan, list of files changed, fresh build/test output (truncated to 2000 chars per output type)
- Role prompts loaded from references/ files (architect from omha-ralplan, security + code reviewer from omha-autopilot)
- Verdicts: APPROVE or REQUEST_CHANGES with specific issues
- On any REQUEST_CHANGES: delegate fix to executor subagent, increment `validation_round`, exit (next invocation re-runs all three reviews)
- Max 3 rounds tracked in `validation_round` state field
- All APPROVE → set `phase: "cleanup"`, exit

---

### Task 7: Implement Phase 5 — Cleanup and Reporting

**Description**: Write Phase 5 — cleanup state files and produce a completion summary. Single invocation.

**Dependencies**: Task 1, Task 6

**Complexity**: Low

**Acceptance Criteria**:
- Deletes: `autopilot-state.json`, `ralph-state.json`, `ralph-tasks.json`, `ralph-cancel.json`, `ralplan-state.json`
- Preserves: `.omha/logs/`, `.omha/plans/`, `.omha/specs/` (audit trail)
- Completion summary includes: original goal, phases completed (with skip notes), total ralph iterations, QA cycles, validation rounds, key files changed
- Handles partial cleanup if some state files don't exist
- Sets `phase: "complete"` before deleting (so if cleanup is interrupted, re-invocation sees complete and retries cleanup)

---

### Task 8: Write Role Prompts for Security and Code Reviewer

**Description**: Create role prompt files for the two reviewer roles new to OMHA: security-reviewer and code-reviewer. These are Phase 4 subagents.

**Dependencies**: None (parallel with other tasks)

**Complexity**: Low

**Acceptance Criteria**:
- `omha-autopilot/references/role-security-reviewer.md` — responsibilities, protocol, output format (APPROVE/REQUEST_CHANGES with issue list)
- `omha-autopilot/references/role-code-reviewer.md` — same structure
- Both are READ-ONLY (analyze and report, don't fix)
- Output format matches what Phase 4 expects to parse
- Follow same format as `omha-ralplan/references/role-architect.md`

---

### Task 9: Write Smart Phase Detection and Multi-Session Resume Logic

**Description**: Implement the artifact detection and multi-session resume logic that makes autopilot work across invocations. This is the core dispatch logic: on ANY invocation, read autopilot-state.json and determine exactly what to do.

**Dependencies**: Task 1

**Complexity**: High (elevated from Medium — this now drives the entire multi-session flow)

**Acceptance Criteria**:
- **Primary dispatch**: Read `autopilot-state.json` → check `context_checkpoint` flag → determine current phase → execute ONE step of that phase
- **Context checkpoint enforcement**: If `context_checkpoint: true`, the skill instructs the agent: "A fresh session is required. Update state to clear the checkpoint flag and exit. The caller must re-invoke in a new session." (In practice, since each invocation IS a new session when the caller loops externally, this flag serves as documentation and a safety check.)
- **Fresh start detection** (no autopilot-state.json): check artifacts in priority order:
  1. `.omha/specs/*-spec.md` with `status: confirmed` → skip Phase 0, create state at Phase 1
  2. `.omha/plans/ralplan-*.md` → skip Phase 0+1, create state at Phase 2
  3. `.omha/state/ralph-state.json` with `phase: "complete"` → skip Phase 0+1+2, create state at Phase 3
  4. Nothing → create state at Phase 0
- **Stale state**: `last_updated_at` older than 2 hours triggers warning
- **Active ralph conflict**: If `ralph-state.json` exists with `active: true` but no `autopilot-state.json`, warn about existing manual ralph session
- Each skip logged: "Skipping Phase 0: confirmed spec found at .omha/specs/foo-spec.md"
- Decision tree documented as a flowchart in SKILL.md preamble

---

### Task 10: Write the Complete SKILL.md

**Description**: Assemble all phases, multi-session dispatch, state management, and pitfalls into the final `omha-autopilot/SKILL.md`. The skill must be self-contained: any invocation reads the skill, reads state, does one step, updates state, exits.

**Dependencies**: Tasks 1-9

**Complexity**: High (elevated from Medium — multi-session dispatch adds complexity)

**Acceptance Criteria**:
- Complete SKILL.md with all 6 phases fully specified
- Frontmatter: name, description, version, tags, category, metadata
- **Architecture section** explaining the one-step-per-invocation pattern and WHY (context accumulation, Hermes depth limits)
- **Dispatch flowchart** as the first thing in the Procedure section
- When to Use / When NOT to Use (NOT for: single tasks, when you want to stay in one session)
- Sentinel convention: how other skills/callers detect autopilot status
- **Caller instructions**: how to invoke autopilot in a loop (manual, cron, script)
  - Manual: "Run autopilot. When it exits, run it again. Repeat until it reports complete."
  - Cron: "Schedule `hermes --skill omha-autopilot --context 'continue autopilot for project X'` every N minutes"
  - Script: "While autopilot-state.json exists and phase != complete: invoke hermes"
- Pitfalls section including:
  - Don't try to loop ralph in a single session (context exhaustion)
  - Don't reimplement ralph — follow ralph's procedure as-is
  - Phase boundaries require fresh sessions — respect context_checkpoint
  - Don't skip QA — ralph verifies per-task, QA catches integration issues
  - Subagent limit: 3 max concurrent (Phase 4 uses all 3)
  - Evidence truncation: always cap build/test output in state
  - Phase 0 is interactive if no spec exists — document honestly

---

### Task 11: Write Caller Loop Examples

**Description**: Create reference examples showing how to invoke autopilot in a loop from different contexts: manual CLI, cron job, shell script wrapper.

**Dependencies**: Task 10

**Complexity**: Low

**Acceptance Criteria**:
- `omha-autopilot/references/caller-examples.md` with:
  - Shell script: `while` loop checking autopilot-state.json phase
  - Cron job: hermes cron configuration
  - Manual: step-by-step user instructions
- Each example includes: how to start, how to monitor progress, how to handle blocked state, how to resume after intervention

---

### Task 12: End-to-End Smoke Test

**Description**: Test the complete autopilot skill on a small, concrete task. Simulate the multi-session pattern by invoking autopilot repeatedly, verifying that each invocation does one step and state progresses correctly.

**Dependencies**: Task 10, Task 11

**Complexity**: High

**Acceptance Criteria**:
- Complete run from idea to verified code on a test project (e.g., "Python CLI that converts CSV to JSON")
- Verify multi-session behavior: each invocation reads state, does one step, updates state, exits
- Verify context_checkpoint enforcement at phase boundaries
- Phase detection works: starting with existing artifacts skips completed phases
- Ralph iterations run one-per-invocation and state tracks iteration count
- QA phase runs in a fresh session context
- Validation phase runs in a fresh session context with 3 parallel reviewers
- Cleanup deletes state files, preserves logs
- Issues documented and fed back into SKILL.md fixes

---

## Risks

### R1: Context Accumulation Within a Single Invocation *(revised)*
Even with one-step-per-invocation, a single ralph iteration (load skill + delegate executor + gather evidence + delegate verifier + update state) consumes 5-12K tokens. This is acceptable — it's well within context limits. The risk is if the skill instructions themselves are too verbose, consuming context before the actual work begins.

**Mitigation**: Keep SKILL.md dispatch logic concise. The agent only needs to read the section relevant to the current phase, not the entire skill. Structure SKILL.md with clear phase headers so the agent can skip irrelevant sections.

### R2: Caller Fails to Re-Invoke
The multi-session design depends on an external caller looping. If the user forgets to re-invoke, or cron stops, autopilot stalls with state sitting on disk.

**Mitigation**: Staleness detection (2-hour warning). Clear exit messages: "Autopilot paused after Phase 2, ralph iteration 3. Re-invoke to continue." Caller loop examples in references/. State files are self-documenting — anyone can read autopilot-state.json and understand progress.

### R3: No Stop Hook — Autopilot Can Be Interrupted
Hermes has no mechanical hook to prevent session exit. The agent may decide to stop mid-step.

**Mitigation**: Strong prompt instructions in SKILL.md. But since each invocation is ONE step, interruption mid-step loses at most one ralph iteration — state from the previous invocation is safe. This is much better than the original design where interruption mid-loop could lose many iterations of accumulated context.

### R4: Subagent Limit (3 concurrent) Constrains Validation
Phase 4 needs exactly 3 parallel reviewers, matching Hermes' limit.

**Mitigation**: Phases are sequential. Phase 2 (ralph) uses executor + verifier (2 subagents max). Phase 4 (validation) uses 3 reviewers. No conflict since phases don't overlap. Within Phase 3 (QA), architect + executor = 2 subagents. All within limits.

### R5: Ralph Blocked State May Require User Input
If ralph enters blocked state, autopilot needs user intervention. This breaks the autonomous promise.

**Mitigation**: Multi-session design makes this natural. Autopilot sets `phase: "blocked"`, reports the issue, and exits. The user resolves the issue, then re-invokes. No different from any other re-invocation — the caller loop just needs a human check when phase is "blocked".

### R6: State File Corruption Between Sessions
Multiple sessions reading/writing the same state files could cause issues if invocations overlap or state is manually edited.

**Mitigation**: Atomic writes (write to .tmp, rename). Single-invocation design means no concurrent autopilot sessions. Warn if `last_updated_at` is very recent (< 30 seconds) — may indicate overlapping invocations. Include `session_id` for traceability.

### R7: Evidence Truncation Loses Important Context
Capping build/test output at 2000 chars may lose important error details.

**Mitigation**: Truncate from the beginning, keep the end (most errors appear at the end of output). Store full output in `.omha/logs/` for human review. The truncated summary in state is for inter-session continuity, not the primary diagnostic source — each fresh session re-runs commands to get fresh full output.

---

## Open Questions

### Q1: Should autopilot support automatic vagueness detection for Phase 0?
For users who already know exactly what they want but don't have a spec file.

**Recommendation**: Yes — implement the vagueness heuristic in Phase 0 and generate inline specs for concrete input. No flag needed; make it automatic. But document clearly that vague input triggers interactive deep-interview.

### Q2: Should autopilot support --skip-qa and --skip-validation flags?
Useful for rapid iteration or when the user wants to handle QA manually.

**Recommendation**: Yes, document as optional configuration in autopilot-state.json (`skip_qa: true`, `skip_validation: true`). Default is full pipeline. Can be set at creation time or by editing state between invocations.

### Q3: How should the caller loop handle Phase 0 interactivity?
Phase 0 (deep-interview) requires user interaction. An automated caller loop (cron/script) can't participate in an interview.

**Recommendation**: Document three strategies:
1. **Pre-run interview**: User runs deep-interview manually before starting autopilot. Autopilot detects the confirmed spec and skips Phase 0.
2. **Concrete input**: User provides detailed enough input that Phase 0 generates an inline spec without interview.
3. **Hybrid**: Caller loop starts, Phase 0 runs interactively with the user present, then subsequent invocations are autonomous.
Strategy 1 is recommended for cron-based automation.

### Q4: Should there be a --pause-after-planning flag?
Allows the user to review the plan before execution starts.

**Recommendation**: Yes — implement as `pause_after_phase` field in autopilot-state.json. When the specified phase completes, autopilot sets `phase: "paused"` instead of advancing. User reviews, changes phase to the next one, and re-invokes. Natural fit for the multi-session design.

### Q5: Where do the reviewer role prompts live?

**Recommendation**: In `omha-autopilot/references/` — they're specific to autopilot's validation phase. Ralplan doesn't use them.

### Q6: What happens with an existing manual ralph session?
Ralph-state.json exists with `active: true` from a previous manual ralph run.

**Recommendation**: Detect and warn. "An active ralph session exists (started {time}). Options: (a) resume it under autopilot control, (b) cancel it and start fresh." Don't silently take over.

### Q7: How many ralph iterations per invocation? *(new)*
Should autopilot do exactly 1 ralph iteration per invocation, or could it batch 2-3?

**Recommendation**: Exactly 1. This is the simplest, safest design and matches ralph's own one-task-per-invocation principle. Batching adds complexity with marginal benefit — the overhead of re-invocation (reading state, loading skill) is small compared to the execution cost. If performance becomes an issue, batching can be added later as an optimization.

### Q8: What's the recommended re-invocation interval for cron? *(new)*
Too fast wastes resources on idle checks. Too slow delays progress.

**Recommendation**: 1-2 minutes for active execution. Each invocation that does work takes 1-5 minutes (one ralph iteration including subagent delegation). A 1-minute cron interval means minimal idle time. Document that the interval can be adjusted based on task complexity.
