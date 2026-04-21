# Round 2 — Planner: omh_delegate Plan (Reconciled)

**Role:** Planner
**Mode:** ralplan
**Phase:** round2-planner
**Subject:** `omh_delegate` — hardened wrapper around `delegate_task`
**Date:** 2026-04-20
**Posture:** Round 1 was the maximalist version. Round 2 is tighter. The
Critic's CI-1/CI-3/CI-4 reframing is largely correct; the Architect's
structural mandates (C1, C5) are also correct. I accept most of both;
where I push back I say so plainly.

---

## 1. Reconciliation Summary

### Critic's critical issues

| Tag  | Concern                                        | Disposition | Reasoning |
|------|------------------------------------------------|-------------|-----------|
| CI-1 | Drop wrapper-persists fallback in v0           | **ACCEPTED** | The fallback hides exactly the failure mode (silent contract erosion) the wrapper exists to surface. v0 ships pure subagent-persists. The fallback only returns in v1+, gated on C0 evidence, and only in the loud form (CI-1 option b). |
| CI-2 | Contract-obedience microbenchmark (C0) as precondition | **ACCEPTED** | One afternoon of work; determines whether the maximalist v1 is justified at all. Promoted to **C0** and made a hard precondition for any v1 fallback decision. |
| CI-3 | Reframe §1: bootstrap shows prose-only works   | **ACCEPTED** | Round 1's framing ("prose alone is degraded mode") is contradicted by the existence of this very ralplan run. Reframed in §2. |
| CI-4 | v0 / v1 / v2 phasing                           | **ACCEPTED** | §3/§4 are restructured around v0/v1/v2. v0 is ~1 day, ~80 LOC + 3 tests. |
| CI-5 | Drop heuristic classifier or require sentinel  | **ACCEPTED** | v0 has no classifier (file-existence check only). If v1 adds rescue, it requires an explicit `<<<RESULT>>>…<<<END_RESULT>>>` sentinel block. No `looks_like_path` regex anywhere. |

### Architect's structural concerns

| Tag | Concern                                       | Disposition | Reasoning |
|-----|-----------------------------------------------|-------------|-----------|
| C1  | Append-only breadcrumb events (mandate)       | **ACCEPTED, MANDATED** | `{id}.dispatched.json` + `{id}.completed.json` (+ `.recovered.json` later). No RMW. Eliminates a whole class of races. Composes naturally with `atomic_write_text`. Critic was right that this should be mandated, not "leaning toward." |
| C2  | OQ1 (delegate_task return shape) blocks B5    | **MOOTED by v0** | Per Critic CI-4: v0 doesn't parse the raw return; it just checks file existence. The blocker dissolves under v0. OQ1 returns as a precondition for any v1 rescue branch. |
| C3  | Split A3                                      | **ACCEPTED** | A3a (layout/seeding policy in `omh_state`) vs A3b (mkdir-at-call-site, folded into B3/B5). v0 only needs A3b inline. |
| C4  | Classifier decision table                     | **ACCEPTED in spirit, REJECTED in form** | Architect's 5-class table is the right shape *if* you keep the rescue branch. Critic CI-5 is correct that `looks_like_path` is heuristic in adversarial space. v0: no classifier. v1 (if rescue lands): sentinel-marker only, two states (`MARKER_PRESENT` / `MARKER_ABSENT`). The classifier as drafted does not ship. |
| C5  | Three-boolean status (mandate)                | **ACCEPTED, MANDATED** | `file_present` / `contract_satisfied` / `recovered_by_wrapper`. Replaces the overloaded `verified`. Even in v0 (where `recovered_by_wrapper` is permanently false), the three booleans ship — keeps the schema stable across phases. |

### Critic's warnings W1–W6

| Tag | Concern                                  | Disposition | Notes |
|-----|------------------------------------------|-------------|-------|
| W1  | Concurrency: Hermes background, multi-orchestrator | **MODIFIED — defer enforcement, document assumption** | v0 assumes single-orchestrator and says so. A `.lock` PID sentinel is overkill for v0. Reconsider in v2 if real bugs surface. |
| W2  | 240-char goal preview is a secret-leak vector | **ACCEPTED** | v0 stores **hash + length only**, no preview. If preview returns in v1, it's behind a regex scrub and explicitly opt-in via `goal_preview=True`. |
| W3  | Silent degrade-to-passthrough is a third codepath | **ACCEPTED** | v0 has no degrade path. If breadcrumb dir is unwritable, raise. `allow_degrade=True` is a v2 knob, not a v0 default. |
| W4  | OQ3 deserves a real answer (project_root discovery) | **ACCEPTED** | v0 walks up from `cwd` looking for `.omh/`, falling back to `cwd` (mirrors `git`'s `.git` discovery). 5 lines. Removes the boundary question. |
| W5  | No operability story for contract violations | **ACCEPTED** | v0 prints a one-line stderr warning on any non-clean dispatch (`ok=False`). Cheap. Catches attention. |
| W6  | Cross-fs `os.replace` failure handling   | **MODIFIED — defer** | v0 raises a clear error with the actual paths and a hint. Auto-detection at startup is v2. Most dev setups don't straddle FUSE inside `.omh/`; punt until a real report surfaces. |

### Architect's M1–M7 (missing)

- M1 (concurrency model) — **stated** as explicit single-orchestrator assumption in v0.
- M2 (`list_dispatches` reader) — **deferred to v2** (only needed once a recovery CLI exists).
- M3 (stale breadcrumbs at startup) — **stated**: ignored, GC is manual.
- M4 (injection position) — **specified**: appended to goal, last block.
- M5 (skill prose specifying a path) — **specified**: wrapper's path always wins, document it.
- M6 (happy-path test first) — **accepted**: v0 test #1 is happy path.
- M7 (project_root discovery) — superseded by W4 (the `.omh/` walk-up).

### Pushbacks (where I disagree)

- **I do not accept "delete the recovery branch forever."** CI-1 is right
  for v0. It is not necessarily right for v1. If C0 measurement shows
  contract-obedience below ~95%, v1 reintroduces the rescue branch in the
  *loud* form (CI-1 option b): sentinel-marker required (CI-5), `ok` becomes
  `"degraded"` not `True`, file carries `<!-- CONTRACT VIOLATED -->`
  header, stderr warning fires, retry-with-hardened-prose is encouraged.
  This is the Critic's option (b), not their preferred (a). I take (b)
  because once the contract is broken in production, "make the orchestrator
  notice" + "still land the bytes" beats "lose the bytes and hope the
  orchestrator retries." The Critic's argument that the rescue removes
  the fix-pressure feedback loop is mitigated by making the rescue *loud*.
- **I do not accept "the wrapper is gilding."** CI-3 reframes it as
  ergonomics rather than correctness, and that reframe is correct — but
  ergonomics here are load-bearing. Without a wrapper, every skill
  hand-rolls path computation, breadcrumbs, and verification in prose.
  That's where the bugs come from. The wrapper is "automating prose that
  is currently working but tedious and lossy at scale." That justifies
  v0; it does not justify the maximalist v1.

---

## 2. Revised Problem Framing (responding to CI-3)

The original framing — "subagent output loss is a correctness bug; the
wrapper fixes it" — is wrong. The bootstrap of this very ralplan run is
proof: no wrapper exists, brutal-prose `<<<EXPECTED_OUTPUT_PATH>>>`
contracts are dispatched, subagents are obeying, artifacts are landing
under `.omh/research/ralplan-omh-delegate/`. Prose-only subagent-persists
is **already working in production** for at least one orchestrator
(Forge, in this session).

The honest framing: **the wrapper is not enabling the pattern; it is
automating it.** Specifically it automates:

1. Path computation (deterministic, mode/phase/round/slug-aware) so skill
   prose stops hand-rolling timestamps.
2. Breadcrumb lifecycle (dispatched/completed events) so a fresh-context
   resumption can reconstruct what was in flight without grepping chat
   logs.
3. Verification (file-exists check post-dispatch) so contract violations
   surface immediately rather than three roles later when a downstream
   reader hits a 404.

That is operational ergonomics. It is worth building. It is not worth
building maximally before measuring. Hence v0.

The bootstrap is also exhibit A for the empirical question CI-2 raised:
**how often is the contract obeyed?** This session has dispatched ~6
subagents so far via brutal-prose contracts. By my count, all 6 have
obeyed. That is n=6, not a benchmark, but it is enough to suspect that
contract-obedience in this regime is high enough that a fallback rescue
branch is dead code 95%+ of the time. C0 turns the suspicion into a
number.

---

## 3. v0 Plan — minimal, measurable, ships fast

**Target:** one PR, one day of work, ~80 LOC of wrapper + ~120 LOC of
tests + one migrated skill phase, exercised on real dispatches to
generate the C0 measurement.

### v0 scope (in)

- One module: `plugins/omh/omh_delegate.py`.
- One function: `omh_delegate(*, role, goal, context="", mode, phase,
  round=None, slug=None, **passthrough) -> dict`.
- Behavior:
  1. Discover project root: walk up from cwd looking for `.omh/`, else
     cwd (W4).
  2. Compute `expected_output_path` =
     `.omh/research/{mode}/{phase}{-r{round}}{-{slug}}-{ts}.md`,
     resolved absolute. `ts = YYYYMMDDTHHMMSSZ`.
  3. `mkdir(parents=True, exist_ok=True)` for both
     `.omh/research/{mode}/` and `.omh/state/dispatched/` (this is the
     A3b inline form — no shared module touched in v0).
  4. Compute `id = "{mode}-{phase}{-r{round}}-{ts}-{rand4}"`.
  5. Write `.omh/state/dispatched/{id}.dispatched.json` via inline
     atomic write (tmp→fsync→`os.replace`). Schema below.
  6. Inject `<<<EXPECTED_OUTPUT_PATH>>>` block + brutal contract,
     **appended** to the goal text (M4).
  7. Call `delegate_task(goal=augmented_goal, **passthrough)`. **Do not
     parse the return.**
  8. Check `Path(expected_output_path).is_file()`.
  9. Write `.omh/state/dispatched/{id}.completed.json` (separate file,
     append-only — Architect C1 option 1, mandated).
  10. Return:
      ```python
      {
          "ok": file_present,                # bool, == file_present in v0
          "path": expected_output_path,      # absolute
          "id": id,
          "file_present": bool,              # v0 source of truth
          "contract_satisfied": bool,        # v0: == file_present
          "recovered_by_wrapper": False,     # always false in v0
          "raw": <delegate_task return>,    # preserved on completion breadcrumb too
      }
      ```
  11. If `not file_present`: print one-line stderr warning (W5),
      preserve `raw` on the completion breadcrumb's `raw_return` field.
      Do **not** write any rescue artifact. Do **not** delete or move
      `expected_output_path`.

### v0 scope (out — explicitly)

- No batch (`tasks=[...]`). v0 is single-task only.
- No rescue/recovery branch. No classifier. No sentinel parsing.
- No `omh_io.py` extraction. v0 inlines its ~10 lines of atomic-write
  and ~5 lines of project-root discovery. (Architect C3 noted A1/A2 are
  worthwhile debt paydown; they are, but not in v0. Land them in v1.)
- No `tools/delegate_tool.py` Hermes-tool registration. v0 is callable
  from skill prose as a Python import. (Tool registration arrives in v1
  once we know we're keeping the shape.)
- No session_id capture. No recovery CLI.
- No `omh-ralph` / `omh-autopilot` migration. v0 migrates **one phase**
  of `omh-ralplan` (planner role) only, as the dogfood case.
- No `goal_preview` field in breadcrumb (W2). Store `goal_sha256` and
  `goal_bytes` only.
- No `degrade-to-passthrough` (W3). If `.omh/` is unwritable, raise.

### v0 breadcrumb schemas

`{id}.dispatched.json`:
```json
{
  "_meta": {"written_at": "...", "schema_version": 1, "kind": "dispatch"},
  "id": "ralplan-round1-planner-20260420T203200Z-a1b2",
  "mode": "ralplan",
  "phase": "round1-planner",
  "round": 1,
  "slug": null,
  "role": "planner",
  "dispatched_at": "2026-04-20T20:32:00Z",
  "expected_output_path": "/abs/.../round1-planner-...-md",
  "goal_sha256": "…",
  "goal_bytes": 1843,
  "context_bytes": 412
}
```

`{id}.completed.json` (separate file, written once, never mutated):
```json
{
  "_meta": {"written_at": "...", "schema_version": 1, "kind": "completed"},
  "id": "ralplan-round1-planner-20260420T203200Z-a1b2",
  "completed_at": "2026-04-20T20:34:11Z",
  "file_present": true,
  "contract_satisfied": true,
  "recovered_by_wrapper": false,
  "bytes": 24170,
  "raw_return_kind": "string|dict|none",
  "raw_return": "<verbatim, capped at 8KB; truncated marker if larger>",
  "error": null
}
```

If `delegate_task` raises: write `{id}.completed.json` with
`file_present=false`, `error="<exception class>: <message>"`, then
re-raise.

### v0 tests (3, plus one optional)

1. **Happy path** (M6 — first test): mock `delegate_task` to actually
   `Path(expected).write_text("hello")` and return the path string.
   Assert `ok=True`, both breadcrumbs present, `file_present=True`,
   `contract_satisfied=True`, `recovered_by_wrapper=False`.
2. **Contract violation**: mock returns prose, no file. Assert
   `ok=False`, `file_present=False`, completion breadcrumb has
   `raw_return` populated, no rescue artifact at `expected_path`,
   stderr warning emitted.
3. **`delegate_task` raises**: mock raises. Assert dispatched
   breadcrumb present, completion breadcrumb has `error`, exception
   re-raised.
4. *(optional)* Path-discovery test: chdir into a nested subdir of a
   tmp `.omh/` repo, assert path resolves under the discovered root.

### v0 dogfood / measurement (C0)

After v0 lands, migrate `omh-ralplan`'s planner-role dispatch only.
Run ralplan against ≥3 trivial specs (toy problems, ~2-round each).
That generates ~10–30 real dispatches. Tally:

- `file_present == True` rate (the headline number).
- For `file_present == False`: classify the `raw_return` by hand into
  `{drift, double-write, refusal, paraphrase, acknowledgment, other}`.

Write the result to
`.omh/research/ralplan-omh-delegate/c0-contract-obedience.md`.

**Decision rule for v1:**
- If `file_present` rate ≥ 95% across ≥20 dispatches: v1 does **not**
  add a rescue branch. Skip straight to batch + helper extraction +
  tool registration + remaining skill migration.
- If 80–95%: v1 adds the rescue branch in **loud-only** form (sentinel
  marker required, `ok="degraded"`, in-band header, stderr).
- If < 80%: stop and fix the contract prose before adding any v1 code.
  The rescue branch is not the right answer; the contract is.

---

## 4. v1 Scope — gated on v0 evidence

v1 runs only after v0 ships and C0 has produced ≥20 dispatches of
data. v1 tasks, in dependency order:

**v1.A — Always-included (regardless of C0 outcome)**

- A1. Extract `omh_io.atomic_write_text(path, content)` from the v0
  inline copy (and from `omh_state.py`). Same acceptance as Round 1 A1.
- A2. Extract `omh_io.resolve_under_project(rel_path)` and
  `omh_io.discover_project_root()`. Refactor `omh_state`,
  `evidence_tool`, and v0's `omh_delegate` to call them. (This is
  Architect C3's A3a + the W4 walk-up consolidated.)
- B6. Batch dispatch (`tasks=[...]`). Per-task breadcrumb and per-task
  `expected_output_path`. Result mapping via the path itself as
  sentinel. Fail-soft semantics (Round 1 Q8). Tests for 3-task batch +
  mixed pass/fail.
- B7. `tools/delegate_tool.py` Hermes registration. Validate
  `mode`/`phase`. Structured error on missing.
- D2/D3/D4. Migrate remaining ralplan phases, then `omh-ralph`,
  `omh-autopilot`, audit `omh-deep-interview`. One per skill.
- E1. Test suite expansion: ≥10 additional unit tests, all 164+
  existing tests still green.
- E2. Update `.omh/README.md` and plugin README — wrapper, schemas,
  layout, recovery procedure (even if recovery CLI is v2).
- E3. Migration guide `.omh/research/ralplan-omh-delegate/migration.md`.

**v1.B — Conditional on C0 (only if `file_present` rate is 80–95%)**

- B5-rescue. Add the rescue branch in **loud-only** form:
  - Goal injection (B4 in Round 1) gains a second sentinel block:
    `<<<RESULT>>>…<<<END_RESULT>>>` — subagent is told that *if* it
    cannot `write_file`, it MUST emit the full artifact between these
    markers in its return string.
  - Wrapper checks: if `file_present == False` AND the raw return
    contains the marker pair, extract content between markers, write
    via `atomic_write_text` to `expected_path` with a *prepended*
    in-band header:
    ```
    <!-- recovered_by_wrapper: contract_satisfied=False -->
    <!-- raw subagent return below -->
    ```
  - Set `file_present=True`, `contract_satisfied=False`,
    `recovered_by_wrapper=True`, `ok="degraded"` (string, not bool —
    callers MUST handle three-state).
  - Write `{id}.recovered.json` as a third event file.
  - stderr warning fires (already fires from W5 — extend message).
  - **No `looks_like_path` heuristic. No content-length threshold. No
    classifier.** Marker-present or marker-absent; binary.
- E1-rescue. Tests for marker-present rescue, marker-absent
  no-rescue, double-write detection (file present AND marker present →
  marker is ignored, `contract_satisfied=True`).

**v1.C — Conditional on C0 (only if `file_present` rate ≥ 95%)**

- *Nothing.* The rescue branch does not ship. The wrapper stays pure
  subagent-persists. CI-1 option (a) wins permanently.

### v1 OQ resolutions (only relevant if v1.B fires)

- OQ1 (`delegate_task` return shape) becomes a hard precondition for
  v1.B work. Investigate before B5-rescue. If the return shape is a
  dict, `raw_return` field handling extends; the marker extraction
  logic operates on `str(raw_return.get('result', raw_return))` or
  similar — exact form deferred to the OQ1 finding.

---

## 5. v2 Scope — operability and recovery

Only after v1 has been live for some real usage (≥1 week of routine
dispatches across ≥2 skills).

- C1. Capture `session_id` from `delegate_task` return (research +
  wire). Add to completion breadcrumb.
- C2. Recovery CLI / tool: `omh_recover --from-id <id>`,
  `omh_recover --list [--only-unverified]`, `omh_recover --gc
  --older-than 14d`. (Subsumes Round 1 M2.)
- W1-followup. Concurrency assertions: `.lock` PID sentinel in
  `.omh/state/dispatched/`. Only if a real multi-orchestrator bug
  surfaces.
- W6-followup. Startup detection of cross-fs `os.replace` situation.
  Only if a real report surfaces.
- C3. Hermes RFE writeup for in-core timeout + pre-dispatch
  session_id hook (FM2 mitigation). Documentation only; no OMH code.
- `allow_degrade=True` knob (W3) if a real read-only-FS use case shows
  up.
- Steered-debate mode RFE (Round 1 Q10) — separate document.

---

## 6. Updated Risks & Open Questions

### Risks (revised)

- **R1' (was R1). Path drift despite injection.** v0 surfaces this
  loudly as `ok=False`. The Critic's CI-5 is right that any future
  rescue must be sentinel-based, not heuristic. Mitigated.
- **R2' (was R2). `delegate_task` return shape.** Mooted in v0 (no
  parsing). Reactivates as a v1.B precondition only.
- **R3 (breadcrumb GC).** Unchanged; deferred to v2.
- **R4 (skill prose drift).** Unchanged; lint check belongs in v1.B
  end-of-track work or v2.
- **R5 (dogfood deadlock).** Unchanged. Still mitigated by orchestrator
  manually persisting this round's artifacts.
- **R6 (plugin import order).** Unchanged.
- **R7 (cross-fs replace).** Deferred to v2 (W6).
- **R8 (NEW — C0 inconclusive).** v0 ships, dogfood produces fewer
  than 20 dispatches, decision rule is unmet. Mitigation: extend
  dogfood window; do not start v1.B speculatively. Worst case: v1.A
  ships on its own and v1.B/v1.C is decided later.
- **R9 (NEW — three-state `ok` breaks callers).** v1.B introduces
  `ok="degraded"`. Callers expecting bool will misbehave. Mitigation:
  v0 already ships `ok` as bool; document v1.B as a breaking-shape
  change for the rescue path; provide `ok_strict: bool` derived field
  (`ok_strict = (ok is True)`) for callers that want a hard pass/fail.

### Open Questions (revised)

- **OQ-A. C0 measurement methodology.** What counts as "obeyed"?
  Proposed: file at exact path, non-empty, written within 30s of
  `delegate_task` return. Alternatives welcome.
- **OQ-B. C0 sample composition.** All planner-role? Mix of roles? I
  propose mixing roles in v0's dogfood specs (planner, architect,
  critic — the actual ralplan triad) so we measure the regime we
  actually run in, not a synthetic best case.
- **OQ-C. v1.B threshold.** I picked 95% / 80% somewhat arbitrarily.
  These are debatable but should be picked *before* C0 runs to avoid
  motivated-reasoning. Locking now: ≥95% = no rescue; 80–95% = loud
  rescue; <80% = fix prose first.
- **OQ-D. Will `.omh/` walk-up discovery work inside Hermes's actual
  cwd at dispatch time?** Need to verify Hermes does not chdir
  unexpectedly. Investigate during v0 implementation.
- **OQ-E. Does the v0 dispatched-then-completed pair survive
  Hermes process restarts mid-dispatch?** The dispatched event lands
  before the call; if Hermes dies between dispatch and completion,
  the breadcrumb dir contains an orphaned `dispatched.json` with no
  `completed.json`. v0 documents this as the expected reconstruction
  signal ("no completion breadcrumb = in-flight or crashed"). v2
  recovery tooling formalizes the cleanup.

---

## 7. Suggested execution order

### v0 (one PR, ~1 day)

1. Implement `plugins/omh/omh_delegate.py` (single file, ~80 LOC).
2. Add `plugins/omh/tests/test_omh_delegate.py` (3 tests + optional
   path-discovery test).
3. Migrate one phase of `omh-ralplan` SKILL.md (planner-role
   dispatch) to call `omh_delegate`.
4. Run ≥20 real dispatches against toy specs; tally results to
   `c0-contract-obedience.md`.
5. Decide v1 shape per the threshold rule.

### v1 (one PR per track, ~1 week)

6. v1.A in parallel: A1+A2 → refactor consumers; B6 batch; B7 tool
   registration; D2/D3/D4 skill migrations; E1/E2/E3 docs+tests.
7. v1.B *only if* C0 said 80–95%: B5-rescue + tests, after OQ1
   investigation completes.

### v2 (later, on demand)

8. C1 session_id, C2 recovery CLI, GC, observability, lock sentinel
   if needed.

---

## 8. What changed from Round 1 (TL;DR)

- **Scope cut by ~70%** for the first ship. v0 is one file, three
  tests, one migrated phase.
- **Rescue branch deleted from v0.** Reintroduced in v1 only if data
  demands it, and only in loud form with sentinel markers (no
  classifier).
- **Append-only breadcrumb events mandated**, not "atomic RMW."
- **Three-boolean status (`file_present`/`contract_satisfied`/
  `recovered_by_wrapper`) mandated** even in v0 where two of them are
  trivially true/false.
- **Project-root discovery via `.omh/` walk-up** (W4) replaces the OMH-
  config-required boundary.
- **Goal preview replaced by `goal_sha256` + `goal_bytes`** (W2).
- **No silent degrade** (W3). Unwritable `.omh/` raises.
- **Bootstrap reframed** as evidence prose-only works, not as
  motivation for the wrapper.
- **C0 microbenchmark added** as a precondition for v1.B/v1.C
  decision.
- **A3, B5, B6, B7, B8, C1, C2, D2-D4, E1-E3 deferred to v1/v2.**

The Critic was right that Round 1 was the maximalist version. Round 2
is the tight one. The Architect was right that the structural fixes
(C1 append-only, C5 three-boolean) belong in the schema from day one,
even when the v0 surface is small enough that they appear over-built.
Building them in now means v1/v2 don't have to migrate the schema.

---

*End of Round 2 Planner.*
