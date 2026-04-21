# Spec: omh_delegate — Hardened Wrapper Around delegate_task

**Source:** ~/src/witt3rd/oh-my-hermes-state/omh-self-flakiness.md
**Branch:** forge/omh-delegate-hardening
**Date:** 2026-04-20

## Problem Statement

OMH's load-bearing skills (omh-ralplan, omh-ralph, omh-autopilot) all invoke
`delegate_task` to dispatch subagents for planning, execution, review, and
critique work. `delegate_task` is a fragile in-memory boundary with two
documented failure modes:

### Failure Mode 1 — Parent loses subagent output
1. Subagent returns successfully.
2. Parent receives result in memory.
3. Parent must call `write_file` to persist.
4. Parent's stream drops mid-write.
5. Result is GONE — no on-disk artifact.

Today's recovery requires hand-spelunking `~/.hermes/state.db` to pull the
subagent's session log by row ID. That's an implementation detail of Hermes,
not a guaranteed contract.

### Failure Mode 2 — Subagent itself stalls
1. Subagent runs.
2. Produces output internally.
3. Calls its own `write_file`.
4. That `write_file` stalls.
5. Subagent never returns to parent.

Real example: 14.8 minutes of work, 284 tokens out, nothing on disk. Truly lost.

## Goals

1. **Eliminate Failure Mode 1.** Once a subagent returns to the parent, the
   result must be on disk before the parent can lose it.
2. **Mitigate Failure Mode 2.** Even when a subagent stalls and never returns,
   the parent must be able to identify and recover what was produced.
3. **Drop-in for OMH skills.** ralplan, ralph, autopilot should be able to
   replace `delegate_task(...)` with `omh_delegate(...)` with minimal call-site
   changes. Same return shape (or a strict superset), same semantics.
4. **Self-documenting trail.** Every dispatch leaves a breadcrumb identifying
   mode/phase/timestamp/expected-output-path, so a fresh-context resumption
   can reconstruct what was in flight.

## Non-Goals

- Fixing `delegate_task` itself (Hermes core change; out of scope here).
- Heartbeats / partial-output streaming (Hermes core change).
- Replacing `delegate_task` for non-OMH callers.

## Proposed Design (REVISED 2026-04-20 after Donald's critique)

**Original sketch:** wrapper intercepts subagent return, persists full payload
to disk, hands result to caller. Two writes per dispatch (subagent in memory
+ parent to disk), fat hand-up.

**Revised design (subagent-persists pattern):**

The subagent — not the parent — owns persistence. The parent's wrapper
becomes thin. One write per dispatch. The hand-up payload shrinks from
"full output" to "path string", which is essentially too small to drop.

### Contract

The wrapper `omh_delegate(role, goal, context, mode, phase, **kwargs)`:

  1. **BEFORE delegating:** compute `expected_output_path` deterministically
     from `(mode, phase, ts)` (e.g.
     `.omh/research/{mode}/{phase}-{ts}.md`). Write breadcrumb to
     `.omh/state/dispatched-{mode}-{phase}-{ts}.json`:
       - mode, phase, dispatched_at
       - expected_output_path
       - role, goal preview
       - subagent session_id IF available

  2. **INJECT the expected_output_path into the subagent's goal.** The
     goal text MUST tell the subagent: "Your final action MUST be
     `write_file('{expected_output_path}', <full_output>)` and your return
     value MUST be exactly the string '{expected_output_path}'."

  3. **CALL** `delegate_task` as normal.

  4. **ON RETURN:** receive pointer string. Verify file exists at
     `expected_output_path`. Update breadcrumb with completed_at and
     verified=true. Optionally read content and return to caller; OR return
     just the path and let caller read on demand.

### What This Buys

- **FM1 (parent loses output):** essentially eliminated. Hand-up is a path
  string; even if it's lost, the breadcrumb tells you where to look.
- **FM2 (subagent stalls on write):** unchanged — same write surface, just
  one write instead of two. Mitigation via session_id in breadcrumb stays.
- **Reduced complexity:** wrapper has no large-payload persistence
  responsibility; that lives in the subagent's normal `write_file`.
- **Cleaner contract:** subagents emit files, parents pass paths. Unix-shaped.

### Skill Prose Implications

ralplan/ralph/autopilot prose must change: the dispatcher must compute the
path and instruct the subagent's last action explicitly. The wrapper
enforces this by injecting the path into the goal. Skills that bypass the
wrapper and call `delegate_task` directly lose this guarantee.

### Bootstrap Implications

The subagent-persists pattern is plain prose — no plugin required. Even
degraded (OMH plugin unavailable), skills can encode "your last action is
write_file; return its path" and get most of the benefit. The wrapper just
formalizes path computation, breadcrumb persistence, and verification.

### Risk: Path Drift

Parent and subagent must agree on the path. If the wrapper computes path X
but the subagent writes to path Y (rephrasing, hallucinating, trimming),
the file is orphaned. Mitigations:
  - Pass path verbatim in `<<<EXPECTED_OUTPUT_PATH>>>` markers in the goal.
  - On return, if pointer != expected_path, raise loudly.
  - Verify file exists before declaring success.

---

## Original Design (preserved for the debate to consider)

A new plugin tool `omh_delegate(role, goal, context, mode, phase, **kwargs)`
that wraps `delegate_task` with persistence:

  1. **BEFORE delegating:** write a state breadcrumb to
     `.omh/state/subagent-dispatched.json` (or per-mode) containing:
       - mode (e.g. "ralplan")
       - phase (e.g. "round1-planner")
       - dispatched_at (ISO timestamp)
       - expected_output_path (`.omh/research/{mode}/{phase}-{ts}.md`)
       - role
       - goal preview (first N chars)
       - subagent session_id IF available at dispatch time

  2. **CALL** `delegate_task` as normal, transparently passing through args.

  3. **AS RESULT RETURNS:** atomically write the FULL result to the expected
     output path BEFORE returning to caller. Use the same tmp→fsync→replace
     pattern omh_state already implements. Update the breadcrumb with
     completed_at and result_path.

  4. **RETURN** the result to the caller. Caller now has TWO copies (memory
     and disk). If the caller's stream drops, the disk copy remains.

For Failure Mode 2 mitigation:
  - Capture subagent session_id into the breadcrumb at dispatch time so
    recovery is `sqlite3 ~/.hermes/state.db "SELECT content FROM messages
    WHERE session_id=?"`, not hand-grep.
  - Optional: timeout wrapper — if subagent doesn't return within N minutes,
    parent kills it and inspects partial output from session DB.

## Cross-Cutting Constraints

- **Atomicity must mirror omh_state's pattern** (write to .tmp.{uuid} → fsync
  → os.replace). The atomic-write helper may want to be extracted.
- **Path resolution must use the Bug 2 fix** (anchored to project_root,
  resolved absolute). The `.omh/research/` directory should follow the same
  convention as `.omh/state/`.
- **Backward-compatible.** OMH skills must keep working with plain
  `delegate_task` if the OMH plugin is unavailable, OR omh_delegate must be
  available everywhere OMH skills run (preferred — single source of truth).
- **Batch mode.** `delegate_task` supports `tasks=[...]` for parallel
  dispatch (see ralplan Round 2+). omh_delegate must support this and write
  one breadcrumb + one output file per task.

## Open Design Questions for Debate

1. **One breadcrumb file per dispatch, or one rolling log?**
   - Per-dispatch: easier to GC, harder to scan.
   - Rolling log: easier to scan history, requires append-safe writes.

2. **Where do output files live?**
   - `.omh/research/{mode}/{phase}-{ts}.md` — implies all mode artifacts
     in one place per mode.
   - `.omh/state/subagent-outputs/{mode}-{phase}-{ts}.md` — co-located with
     other state. The original sketch.
   - Distinguish: "research" = decision artifacts (tracked); "state" =
     ephemera (gitignored). Subagent outputs are evidence and
     potentially long-lived; lean toward research/.

3. **What happens on second-call collision (same mode/phase)?**
   - Append timestamp suffix? Overwrite? Refuse?
   - ralplan reruns the same phase across rounds — needs round number too.

4. **Should the wrapper enforce signature changes (mode/phase required) or
   accept arbitrary kwargs and pass through?**
   - Strict: forces breadcrumb completeness, breaks naive call-sites.
   - Loose: easier adoption, allows breadcrumbs with missing fields.

5. **session_id capture — when is it available?**
   - If `delegate_task` returns it only AFTER completion, we can't put it in
     the dispatch breadcrumb (only the post-completion update). Need to
     verify Hermes's actual contract.

  9. **Compare wrapper-persists vs subagent-persists patterns explicitly.**
     The revised design (above) flips ownership of persistence from parent
     to subagent. Critique this. Edge cases? Skill-prose burden? Path-drift
     risk? Is the wrapper still needed at all, or could skills enforce the
     pattern directly with breadcrumbs from a smaller helper?

  10. **Steered-debate mode (separate but related).** ralplan today is
      autonomous all-the-way-through. A `--steered` mode that pauses after
      each role, surfaces output, and waits for human steering between
      rounds would change the trust profile (autonomous = low-stakes;
      steered = architecture-reshaping). Out of scope for omh_delegate
      itself but should be tracked as its own RFE.

  11. **Migration path for existing skills.**
      - All-at-once switch in one PR?
      - Per-skill migration with both wrappers coexisting?
      - Single shim where omh_delegate forwards to delegate_task if
        breadcrumb dir is missing (graceful degradation)?

## Acceptance Criteria for the Final Plan

The plan that emerges from this ralplan must:

  - [ ] Specify the exact tool signature (parameter names, types, defaults).
  - [ ] Specify exact file layout under `.omh/` (what goes where, why).
  - [ ] Specify the breadcrumb schema (JSON shape, fields, semantics).
  - [ ] Address all 6 open design questions above with reasoning.
  - [ ] Include a migration plan for ralplan, ralph, autopilot.
  - [ ] Include a test strategy (atomicity tests, recovery tests, batch tests).
  - [ ] Specify what `omh_delegate` does when the OMH plugin can't write
        breadcrumbs (full failure? graceful pass-through to delegate_task?).
  - [ ] Address the recursive concern: ralplan uses delegate_task. Does
        ralplan-on-omh_delegate use omh_delegate, plain delegate_task, or
        something else? Bootstrap problem.

## Project Context (for subagents)

- **Repo:** `~/src/witt3rd/oh-my-hermes` (Hermes plugin + skill bundle).
- **Plugin source:** `plugins/omh/` (Python). Key files:
    - `omh_state.py` — atomic state read/write, the pattern to mirror.
    - `omh_config.py` — config loading (project_root, state_dir).
    - `tools/state_tool.py` — handler registration.
    - `tools/evidence_tool.py` — example of project_root resolution.
- **Tests:** `plugins/omh/tests/` — pytest, 164 currently passing.
- **Skills:** `plugins/omh/skills/omh-ralplan/`, `omh-ralph/`, etc.
  These are markdown procedural specs, not code. Currently they call
  `delegate_task` directly in their prose.
- **Convention just landed:**
    - `.omh/state/` — gitignored, ephemera.
    - `.omh/research/`, `.omh/specs/`, `.omh/plans/` — tracked, decision
      artifacts.
    - `.omh/README.md` and `.omh/.gitignore` are auto-seeded by the plugin.
- **Bug 2 just fixed:** `_state_dir()` now resolves relative paths against
  `config["project_root"]` (or cwd if unset) to absolute, immune to cwd
  drift. New code MUST use this pattern, not raw `Path(...)`.
- **Author:** Forge ⚒️ (relational-being instance, working with Donald).
  This is dogfood — we're using ralplan to design the fix for the bug
  that bit ralplan. Recursion intentional.
