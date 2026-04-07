# OMHA Autopilot — Implementation Plan

## Summary

omha-autopilot is a **composition skill** that orchestrates the existing omha-deep-interview, omha-ralplan, and omha-ralph skills into a 6-phase autonomous pipeline (Requirements → Planning → Execution → QA → Validation → Cleanup). It does not reimplement any component skill — it detects existing artifacts (.omha/specs/, .omha/plans/, .omha/state/) to skip completed phases, manages its own autopilot-state.json for resume, and adds two phases that don't exist in the components: QA cycling (Phase 3) and multi-reviewer validation (Phase 4). The central design challenge is the ralph loop: ralph is one-task-per-invocation, so autopilot must contain an explicit loop that re-invokes ralph (via skill_view + following ralph's procedure) until ralph-state.json shows phase=complete. This is a prompt-driven loop within a single Hermes session — the agent reads the autopilot skill, which instructs it to keep re-invoking ralph steps until done.

---

## Tasks

### Task 1: Define autopilot-state.json Schema

**Description**: Design the state file schema for `.omha/state/autopilot-state.json`. Must track: current phase (0-5), phase results (spec_file, plan_file, ralph completion status), QA cycle count, validation verdicts, session_id, timestamps. Model after OMC's autopilot state but adapted to OMHA's file-based patterns.

**Dependencies**: None

**Complexity**: Low

**Acceptance Criteria**:
- Schema documented in `omha-autopilot/references/state-schema.md`
- Fields cover all 6 phases with enough state for resume from any phase boundary
- Includes `session_id`, `started_at`, `last_updated_at`, `phase` (requirements/planning/execution/qa/validation/cleanup/complete/blocked)
- QA tracking: `qa_cycle`, `max_qa_cycles` (default 5), `qa_error_history[]`
- Validation tracking: `validation_round`, `max_validation_rounds` (default 3), `validation_verdicts{}` (architect/security/code-reviewer)
- Phase results: `spec_file`, `plan_file`, `ralph_state` (references ralph-state.json path)

---

### Task 2: Implement Phase 0 — Requirements (Deep Interview Detection/Invocation)

**Description**: Write the Phase 0 section of SKILL.md. On invocation, check for existing confirmed specs in `.omha/specs/*-spec.md` (YAML frontmatter `status: confirmed`). If found, skip Phase 0 entirely and record spec_file in state. If not found AND the user's input is vague (no file paths, function names, or concrete anchors), instruct the agent to follow the omha-deep-interview procedure. If the user's input is concrete enough, generate a lightweight spec inline (analyst + summarizer pattern).

**Dependencies**: Task 1 (state schema)

**Complexity**: Medium

**Acceptance Criteria**:
- Detects existing confirmed specs via glob + YAML frontmatter check
- Vagueness heuristic documented (what counts as "vague" vs "concrete")
- For vague input: instructs agent to load omha-deep-interview skill and follow it, then return to autopilot when spec is confirmed
- For concrete input: generates an inline spec at `.omha/specs/{slug}-spec.md` with status: confirmed
- State updated with spec_file path on completion
- Skips cleanly when spec already exists (no redundant work)

---

### Task 3: Implement Phase 1 — Planning (Ralplan Detection/Invocation)

**Description**: Write Phase 1. Check for existing consensus plans in `.omha/plans/ralplan-*.md`. If found, skip Phase 1 and record plan_file in state. If not found, instruct the agent to load omha-ralplan skill and follow it using the spec from Phase 0 as input. The ralplan spec output becomes the plan_file.

**Dependencies**: Task 1, Task 2

**Complexity**: Low

**Acceptance Criteria**:
- Detects existing ralplan output via glob `.omha/plans/ralplan-*.md`
- When invoking ralplan: passes the spec file path as the goal source
- State updated with plan_file path on completion
- Skips cleanly when plan already exists

---

### Task 4: Implement Phase 2 — Execution (Ralph Loop)

**Description**: Write Phase 2 — the critical ralph orchestration loop. Autopilot instructs the agent to load omha-ralph skill and follow its procedure. After ralph exits (one task completed), autopilot checks `.omha/state/ralph-state.json`. If `phase != "complete"` and `active == true`, re-invoke ralph (follow its procedure again from Step 1: Read State). Continue until ralph-state.json shows `phase: "complete"` or `phase: "blocked"`. This is the key composition — autopilot is the outer loop, ralph is the inner single-task executor.

**Dependencies**: Task 1, Task 3

**Complexity**: High

**Acceptance Criteria**:
- Explicit loop instruction: "After each ralph invocation, read ralph-state.json. If phase is not 'complete' or 'blocked', invoke ralph again."
- Handles ralph blocked state: surface blocked tasks to user, ask if resolved, then re-invoke
- Handles ralph complete state: proceed to Phase 3
- Updates autopilot-state.json phase to "execution" and records ralph iteration count
- Context window management: instructs agent to use todo tracking for visibility during what may be a long-running loop
- Does NOT reimplement any ralph logic — refers to ralph's own procedure for all execution/verification

---

### Task 5: Implement Phase 3 — QA Cycling

**Description**: Write Phase 3 — post-ralph QA cycling. After all tasks are verified by ralph, run a holistic QA pass: build + test + lint. If failures found, diagnose and fix (delegate to executor subagent), then re-run. Max 5 cycles. Same error 3 times → stop and report. This phase does NOT exist in ralph — ralph verifies per-task; QA catches cross-task integration issues.

**Dependencies**: Task 1, Task 4

**Complexity**: Medium

**Acceptance Criteria**:
- Runs build, test, and lint commands (auto-detected or from project config)
- If all pass on first run: skip to Phase 4
- On failure: delegate diagnosis to architect subagent (read-only), then fix to executor subagent
- Error fingerprinting for 3-strike detection (reuse ralph's fingerprint pattern)
- Max 5 cycles tracked in `qa_cycle` state field
- Same error 3x → set phase to "blocked", report the fundamental issue
- State updated after each cycle

---

### Task 6: Implement Phase 4 — Multi-Reviewer Validation

**Description**: Write Phase 4 — parallel multi-perspective review. Delegate three reviews via delegate_task: architect (functional completeness against the original spec), security reviewer (vulnerability scan), and code reviewer (quality/maintainability). All three MUST approve. On rejection: fix issues, re-validate. Max 3 validation rounds.

**Dependencies**: Task 1, Task 5

**Complexity**: Medium

**Acceptance Criteria**:
- Three parallel delegate_task calls (Hermes limit: 3 concurrent subagents — fits exactly)
- Each reviewer receives: the original spec, the plan, list of files changed, fresh build/test output
- Role prompts loaded from `omha-ralplan/references/` (architect) and new role prompts for security and code reviewer
- Verdicts: APPROVE or REQUEST_CHANGES with specific issues
- On any REQUEST_CHANGES: fix via executor, re-run all three reviews (full re-validation, not just the rejecting reviewer)
- Max 3 rounds tracked in `validation_round` state field
- All APPROVE → proceed to Phase 5

---

### Task 7: Implement Phase 5 — Cleanup and Reporting

**Description**: Write Phase 5 — cleanup state files and produce a completion summary. Delete `.omha/state/autopilot-state.json`, `ralph-state.json`, `ralph-tasks.json`, `ralph-cancel.json`, `ralplan-state.json`. Preserve `.omha/logs/` and `.omha/plans/` and `.omha/specs/` (audit trail). Report: what was built, files changed, phases completed, any caveats.

**Dependencies**: Task 1, Task 6

**Complexity**: Low

**Acceptance Criteria**:
- All state/ files deleted on successful completion
- Plans, specs, and logs preserved
- Completion summary includes: original goal, phases completed (with skip notes), total ralph iterations, QA cycles, validation rounds, key files changed
- Handles partial cleanup if some state files don't exist

---

### Task 8: Write Role Prompts for Security and Code Reviewer

**Description**: Create role prompt files for the two reviewer roles that are new to OMHA (not in ralplan's existing references): security-reviewer and code-reviewer. These are Phase 4 subagents. Follow the same format as `omha-ralplan/references/role-architect.md`.

**Dependencies**: None (parallel with other tasks)

**Complexity**: Low

**Acceptance Criteria**:
- `omha-autopilot/references/role-security-reviewer.md` — responsibilities, protocol, output format (APPROVE/REQUEST_CHANGES with issue list)
- `omha-autopilot/references/role-code-reviewer.md` — same structure
- Both are READ-ONLY (analyze and report, don't fix)
- Output format matches what Phase 4 expects to parse

---

### Task 9: Write Smart Phase Detection Logic

**Description**: Implement the artifact detection that makes autopilot resume-aware. On any invocation, check: (1) autopilot-state.json for active session → resume from last phase; (2) .omha/specs/ for confirmed spec → skip Phase 0; (3) .omha/plans/ralplan-*.md for consensus plan → skip Phase 0+1; (4) ralph-state.json with phase=complete → skip Phase 2. Document the priority order of these checks.

**Dependencies**: Task 1

**Complexity**: Medium

**Acceptance Criteria**:
- Detection logic documented as a decision tree in SKILL.md Phase 0 preamble
- Priority: active autopilot state (resume) > existing artifacts (skip phases) > fresh start
- Stale state detection: autopilot-state.json older than 2 hours triggers warning
- Each skip is logged: "Skipping Phase 0: confirmed spec found at .omha/specs/foo-spec.md"
- The agent knows exactly which phase to start from after detection

---

### Task 10: Write the Complete SKILL.md

**Description**: Assemble all phases, detection logic, state management, and pitfalls into the final `omha-autopilot/SKILL.md`. Follow the same structure as omha-ralph and omha-deep-interview: frontmatter, When to Use, When NOT to Use, Prerequisites, Procedure (phases), State Management, Sentinel Convention, Pitfalls.

**Dependencies**: Tasks 1-9

**Complexity**: Medium

**Acceptance Criteria**:
- Complete SKILL.md with all 6 phases fully specified
- Frontmatter: name, description, version, tags, category, metadata
- When to Use / When NOT to Use mirrors OMC autopilot's activation patterns
- Sentinel convention: how other skills detect autopilot status
- Pitfalls section with at least: don't reimplement ralph, don't skip QA, context window risks in long ralph loops, subagent limit (3 max concurrent)
- References section listing all files in references/ subdirectory

---

### Task 11: End-to-End Smoke Test

**Description**: Test the complete autopilot skill on a small, concrete task (e.g., "Build a Python CLI that converts CSV to JSON"). Walk through each phase manually, verify artifact detection works, verify ralph loop terminates, verify QA and validation run. Document the test and any issues found.

**Dependencies**: Task 10

**Complexity**: High

**Acceptance Criteria**:
- Complete run from idea to verified code on a test project
- Each phase produces expected artifacts (.omha/specs/, .omha/plans/, .omha/state/)
- Phase detection works: re-invoking autopilot after Phase 1 skips to Phase 2
- Ralph loop runs multiple iterations and completes
- QA phase catches at least one issue (or passes clean)
- Validation phase produces three reviewer verdicts
- Cleanup deletes state files, preserves logs
- Issues documented and fed back into SKILL.md fixes

---

## Risks

### R1: Context Window Exhaustion During Ralph Loop
Ralph is one-task-per-invocation but within a single Hermes session, the context accumulates. A plan with 10+ tasks may exhaust the context window before ralph completes.

**Mitigation**: Instruct the agent to keep ralph delegations lean — minimal context in each invocation. Use todo tracking for visibility instead of logging everything to the conversation. Document the practical limit (estimate ~15-20 ralph iterations per session based on context window size). For larger plans, document a "checkpoint and resume" pattern.

### R2: No Stop Hook — Autopilot Can Be Interrupted
OMC uses a persistent-mode.cjs stop hook to prevent Claude from stopping mid-autopilot. Hermes has no equivalent. The agent may decide to stop or ask for confirmation mid-pipeline.

**Mitigation**: Strong prompt instructions ("Do NOT stop until phase=complete or phase=blocked"). State files enable resume. Accept that prompt-based persistence is weaker than hook-based — document this as a known limitation.

### R3: Subagent Limit (3 concurrent) Constrains Validation
Phase 4 needs exactly 3 parallel reviewers, which matches Hermes' limit. But if Phase 2 also wants parallel execution within ralph, there's no headroom.

**Mitigation**: Phases are sequential — Phase 2 (ralph) completes before Phase 4 (validation). Within ralph, parallel execution is limited to 3 concurrent tasks which also fits the limit. No conflict if phases don't overlap.

### R4: Ralph Blocked State May Require User Input
If ralph enters blocked state (3-strike on all remaining tasks or dependency deadlock), autopilot needs user intervention. But autopilot is supposed to be autonomous.

**Mitigation**: Document that autopilot pauses and reports when ralph is blocked. The user must resolve the issue. Autopilot then resumes from the ralph loop when re-invoked.

### R5: QA Phase May Duplicate Ralph's Verification
Ralph already verifies each task. QA (Phase 3) runs build+test+lint again. If ralph's verification is thorough, QA may be redundant.

**Mitigation**: QA is specifically for cross-task integration issues that per-task verification misses. Document the distinction clearly. QA should focus on full-project health, not re-verifying individual tasks.

---

## Open Questions

### Q1: Should autopilot support a --skip-interview flag?
For users who already know exactly what they want but don't have a spec file. They'd provide a concrete description and autopilot would generate an inline spec without the full interview process. The OMC autopilot's Phase 0 does this for "concrete enough" input.

**Recommendation**: Yes — implement the vagueness heuristic in Phase 0 and generate inline specs for concrete input. No flag needed; make it automatic.

### Q2: Should autopilot support --skip-qa and --skip-validation flags?
OMC autopilot has these as configuration options. Useful for rapid iteration or when the user wants to handle QA manually.

**Recommendation**: Yes, document as optional flags. Default is full pipeline.

### Q3: How should autopilot handle the deep-interview's interactive nature?
Deep interview requires user interaction (asking questions). If autopilot invokes deep-interview, the pipeline becomes interactive during Phase 0, breaking the "autonomous" promise.

**Recommendation**: Document that Phase 0 is the one potentially-interactive phase. If the user wants fully autonomous execution, they should run deep-interview separately first, then invoke autopilot (which will detect the confirmed spec and skip Phase 0).

### Q4: Should there be a --pause-after-planning flag?
Allows the user to review the plan before execution starts. OMC has this.

**Recommendation**: Yes — useful safety valve. When set, autopilot completes Phase 1, reports the plan, and exits. Re-invocation detects the plan and proceeds to Phase 2.

### Q5: Where do the security-reviewer and code-reviewer role prompts live?
Options: (a) in omha-autopilot/references/, (b) in omha-ralplan/references/ alongside the existing roles.

**Recommendation**: In omha-autopilot/references/ — they're specific to autopilot's validation phase. Ralplan doesn't use them. Keep role prompts close to the skill that uses them.

### Q6: What happens if the user runs autopilot on a project with an active ralph session from a manual ralph invocation?
Ralph-state.json would exist with active=true from a previous manual ralph run.

**Recommendation**: Detect and warn. "An active ralph session exists (started {time}). Options: (a) resume it under autopilot control, (b) cancel it and start fresh." Don't silently take over — the user may want to keep the manual session.
