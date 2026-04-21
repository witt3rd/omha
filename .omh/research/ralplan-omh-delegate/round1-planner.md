# Round 1 — Planner: omh_delegate Implementation Plan

**Role:** Planner
**Mode:** ralplan
**Phase:** round1-planner
**Subject:** `omh_delegate` — hardened wrapper around `delegate_task`
**Date:** 2026-04-20

---

## 1. Summary

Build `omh_delegate` as a thin Python wrapper around Hermes's `delegate_task`
that implements the **subagent-persists pattern as primary**, with a
**wrapper-side verify-and-rescue fallback as secondary** (i.e., a hybrid that
is "subagent-persists by contract, wrapper-persists on miss"). The wrapper
deterministically computes an `expected_output_path` under
`.omh/research/{mode}/{phase}-r{round}-{slug}-{ts}.md`, drops a breadcrumb
under `.omh/state/dispatched/{id}.json` *before* calling `delegate_task`,
injects the path into the subagent's goal via verbatim `<<<…>>>` markers
demanding `write_file` as the subagent's last action, then on return verifies
the file exists. If the subagent returned content but no file (drift,
hallucination, refusal), the wrapper itself atomically writes the returned
payload to `expected_output_path` (belt-and-suspenders). Breadcrumb is
updated with `completed_at`, `verified`, `bytes`, and `recovered_by_wrapper`
flags. Batch dispatch is supported by fan-out: one breadcrumb + one path per
task. Path resolution and atomic writes reuse the `omh_state.py` Bug-2-fixed
helpers (extracted into `omh_io.py`). Skills migrate one at a time behind a
shim that falls back to `delegate_task` if the plugin is unavailable.

**Why hybrid (subagent-persists primary, wrapper-persists fallback):**

- Subagent-persists wins on the *common path*: one write, small hand-up
  (path string), Unix-shaped, robust to parent stream drops (FM1).
- Wrapper-persists wins on the *failure path*: subagent ignores the
  contract or returns prose instead of writing — the wrapper still has the
  payload in memory and can land it.
- Cost of doing both is small: the wrapper already has the return value;
  writing it on the fallback branch is ~5 lines.
- Pure subagent-persists leaves a real hole when the subagent
  rephrases/forgets the contract. Pure wrapper-persists incurs two writes
  per dispatch and a fat hand-up. The hybrid pays the second write *only
  when needed*.

This does **not** address Failure Mode 2 (subagent stalls and never
returns) on its own — that requires session-id capture + recovery tooling,
which is included as a separate task track.

---

## 2. Tasks

Tasks are grouped into tracks. Within a track, dependencies are explicit.
Across tracks, items with no listed dependency may run in parallel.

### Track A — Foundations (shared helpers)

**A1. Extract `omh_io.atomic_write_text(path, content)`**
- What: Pull the tmp→fsync→`os.replace` pattern out of `omh_state.py` into
  a reusable `plugins/omh/omh_io.py`. `omh_state.py` calls it.
- Deps: none.
- Complexity: small.
- Acceptance:
  - All 164 existing tests still pass.
  - New unit test: write under a tmp_path, kill mid-write simulation
    (write to `.tmp.*`, assert `os.replace` is the only mutation of the
    final path).
  - Function rejects non-absolute paths or auto-resolves via
    `Path(path).resolve()`.

**A2. Extract `omh_io.resolve_under_project(rel_path)`**
- What: Centralize the Bug-2-fixed path resolution (anchor to
  `config["project_root"]` else `Path.cwd()`, then `.resolve()`). Used by
  `omh_state`, `evidence_tool`, and the new `omh_delegate`.
- Deps: A1 (same module landing).
- Complexity: small.
- Acceptance:
  - `omh_state._state_dir()` and `evidence_tool` both refactored to call
    it; their tests still pass.
  - Unit test: chdir into a subdir, ensure resolution still anchors at
    project_root.

**A3. Add `.omh/research/{mode}/` and `.omh/state/dispatched/` seeding**
- What: When `omh_delegate` writes its first artifact, ensure the parent
  directories exist (`mkdir(parents=True, exist_ok=True)`) and that the
  `.omh/README.md`/`.gitignore` auto-seed logic in `omh_state` covers
  `state/dispatched/` (gitignored) and `research/` (tracked).
- Deps: A2.
- Complexity: small.
- Acceptance:
  - Fresh repo: invoking `omh_delegate` once creates both dirs.
  - `.omh/.gitignore` contains `state/` (already does) — verify
    `state/dispatched/` is covered.
  - `research/` is *not* gitignored.

### Track B — Core wrapper

**B1. Define `omh_delegate` signature and module skeleton**
- What: Create `plugins/omh/omh_delegate.py` with the function signature
  and docstring. No logic yet.
- Signature (final):
  ```python
  def omh_delegate(
      *,
      role: str,
      goal: str,
      context: str = "",
      mode: str,                       # required (ralplan/ralph/autopilot/...)
      phase: str,                      # required (round1-planner, exec-step3, ...)
      round: int | None = None,        # optional, suffixed into path if given
      slug: str | None = None,         # optional, short human tag
      tasks: list[dict] | None = None, # batch mode; if set, role/goal ignored
      timeout_s: int | None = None,    # forwarded to delegate_task if supported
      overwrite: str = "suffix",       # "suffix" | "overwrite" | "refuse"
      return_content: bool = False,    # if True, read file and include in result
      **passthrough,                   # forwarded to delegate_task
  ) -> dict
  ```
- Return shape (single):
  ```python
  {
      "ok": bool,
      "path": str,            # absolute expected_output_path
      "breadcrumb": str,      # absolute path to breadcrumb json
      "verified": bool,       # file exists at path
      "recovered_by_wrapper": bool,  # True if subagent didn't write, wrapper did
      "session_id": str | None,
      "bytes": int,
      "content": str | None,  # populated only if return_content=True
      "raw": Any,             # original delegate_task return
  }
  ```
- Return shape (batch): `{"ok": bool, "results": [<single>, ...]}`.
- Deps: none.
- Complexity: small.
- Acceptance: module imports clean, mypy/pyright (if used) passes, no
  tests yet.

**B2. Path computation: `_compute_expected_path(mode, phase, round, slug, ts)`**
- What: Deterministic, collision-aware. Pattern:
  `.omh/research/{mode}/{phase}{-r{round}}{-{slug}}-{ts}.md` where `ts` is
  `YYYYMMDDTHHMMSSZ`. Resolved under project root via A2.
- Deps: A2, B1.
- Complexity: small.
- Acceptance:
  - Unit tests for each combination (with/without round, with/without
    slug).
  - Collision policy honored (see Q3 below).

**B3. Breadcrumb writer: `_write_dispatch_breadcrumb(...)`**
- What: Write JSON to `.omh/state/dispatched/{mode}-{phase}-{ts}-{rand4}.json`
  using `omh_io.atomic_write_text`. Schema:
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
    "completed_at": null,
    "expected_output_path": "/abs/.../round1-planner-...-md",
    "goal_preview": "first 240 chars...",
    "context_bytes": 1843,
    "session_id": null,
    "verified": false,
    "recovered_by_wrapper": false,
    "bytes": null,
    "error": null
  }
  ```
- Deps: A1, A3, B2.
- Complexity: small.
- Acceptance:
  - Unit test: dispatch breadcrumb written before any `delegate_task`
    call (mock `delegate_task`, assert breadcrumb file exists at the
    point the mock is invoked).
  - Atomic: simulated crash mid-write leaves no partial file.

**B4. Goal injection: `_inject_path_contract(goal, expected_path)`**
- What: Append a structured trailer to the goal text:
  ```
  <<<EXPECTED_OUTPUT_PATH>>>
  /abs/.../round1-planner-...-md
  <<<END_EXPECTED_OUTPUT_PATH>>>

  CRITICAL — your final action MUST be exactly:
    write_file('<that exact path>', <your_full_output_as_markdown>)
  And your return value MUST be exactly the string:
    '<that exact path>'
  Do not summarize, paraphrase, or alter the path. The file IS the
  deliverable. The path is the receipt.
  ```
- Deps: B2.
- Complexity: small.
- Acceptance:
  - Unit test: marker block present; path appears verbatim; instructions
    present.
  - Idempotent: re-injecting on already-injected goal does not duplicate.

**B5. Core dispatch flow (single task)**
- What: Compose B2/B3/B4 around a single `delegate_task` call. On return:
  1. parse pointer from raw return (string path or dict with path field);
  2. verify file exists at expected_path;
  3. if missing AND raw return contains substantive content (>32 chars),
     wrapper writes it via `omh_io.atomic_write_text` and sets
     `recovered_by_wrapper=True`;
  4. update breadcrumb with `completed_at`, `verified`, `bytes`,
     `session_id`, `recovered_by_wrapper`;
  5. return the dict from B1.
- Deps: B1–B4, A1, A2.
- Complexity: medium.
- Acceptance:
  - Mock `delegate_task` returning correct path string → ok=True,
    verified=True, recovered=False.
  - Mock returning content string but no write → wrapper recovers,
    verified=True, recovered=True.
  - Mock returning empty/whitespace → ok=False, error populated,
    breadcrumb updated with error.
  - Mock raising → breadcrumb updated with error, exception re-raised.

**B6. Batch dispatch (`tasks=[...]`)**
- What: For each task dict, compute its own path/breadcrumb (phase may be
  shared; slug per-task disambiguates), call `delegate_task(tasks=[...])`
  once with augmented goals, then post-process per-result. If
  `delegate_task` doesn't preserve order, use a per-task injected
  sentinel (the path itself works) to map results back.
- Deps: B5.
- Complexity: medium.
- Acceptance:
  - 3-task batch test: 3 breadcrumbs, 3 files, 3 results in `results`.
  - Mixed pass/fail batch: per-task `ok` flags correct; one recovered
    branch tested.

**B7. Tool registration: `tools/delegate_tool.py`**
- What: Hermes handler that exposes `omh_delegate` to the agent. Mirror
  `tools/state_tool.py` style. Validate required kwargs (mode, phase),
  surface helpful error messages.
- Deps: B5.
- Complexity: small.
- Acceptance:
  - Tool listed by Hermes plugin discovery.
  - Missing `mode` returns structured error, not exception.

**B8. Plugin-unavailable fallback shim**
- What: A *prose-level* fallback (documented in skill SOPs) and a
  *Python-level* fallback in the wrapper: if `delegate_task` is not
  importable, raise a clear error. If the plugin loads but
  `.omh/state/dispatched/` is unwritable (read-only FS, permission),
  log + degrade to plain `delegate_task` passthrough returning
  `{"ok": True, "path": None, "verified": False, "raw": ...}`.
- Deps: B5.
- Complexity: small.
- Acceptance:
  - Test with monkeypatched unwritable dir: returns passthrough, no
    crash, warning logged.

### Track C — FM2 mitigation (subagent stall)

**C1. Capture `session_id` from `delegate_task`**
- What: Investigate Hermes `delegate_task` return contract. If
  session_id is in the return dict, capture post-completion. If Hermes
  emits a pre-dispatch hook or callback exposing it earlier, wire that.
  Otherwise document the limitation.
- Deps: none (research task).
- Complexity: small.
- Acceptance:
  - Written finding in `.omh/research/ralplan-omh-delegate/notes-session-id.md`.
  - If available, B5 stores it in breadcrumb.

**C2. Recovery CLI: `omh_recover --from-breadcrumb <id>`**
- What: A small script (or Hermes tool) that reads a breadcrumb and, if
  `verified=false` and `session_id` present, queries `~/.hermes/state.db`
  for the session messages and writes them to `expected_output_path`.
- Deps: C1.
- Complexity: medium.
- Acceptance:
  - Integration test with a synthetic state.db row → recovery produces
    file at expected path; breadcrumb updated with
    `recovered_by_cli=True`.

**C3. Optional timeout enforcement (out of scope for v1; tracked)**
- What: If `delegate_task` supports a timeout, forward it. Otherwise
  document as a Hermes RFE.
- Deps: C1.
- Complexity: small (research) / large (if implemented in OMH).
- Acceptance: written RFE in `.omh/research/`.

### Track D — Skill migration

**D1. Migrate `omh-ralplan/SKILL.md`**
- What: Replace `delegate_task(...)` invocations in the prose with
  `omh_delegate(...)`. Add `mode="ralplan"`, `phase="roundN-{role}"`,
  `round=N`. Update example return handling to read from `result.path`.
- Deps: B7.
- Complexity: medium.
- Acceptance:
  - End-to-end ralplan dry run on a trivial spec produces N breadcrumbs
    + N research files; orchestrator reads from disk, not memory.

**D2. Migrate `omh-ralph/SKILL.md`**
- Deps: D1 pattern proven.
- Complexity: small.
- Acceptance: ralph step produces breadcrumb + file.

**D3. Migrate `omh-autopilot/SKILL.md`**
- Deps: D1 pattern proven.
- Complexity: small.
- Acceptance: autopilot phase produces breadcrumb + file.

**D4. Update `omh-deep-interview` if it dispatches**
- Deps: audit first.
- Complexity: small.

### Track E — Tests & docs

**E1. Test suite for `omh_delegate`** (unit + integration)
- Atomicity: simulated crash leaves no partial breadcrumb/output.
- Recovery branch: subagent returns content, no file → wrapper writes.
- Path drift: subagent returns *different* path → wrapper logs mismatch,
  prefers expected_path, writes content there if available, marks
  `recovered_by_wrapper=True`, records `subagent_returned_path` in
  breadcrumb.
- Batch: 3 parallel tasks, mixed outcomes.
- Plugin-unavailable: graceful passthrough.
- Conftest mirrors existing pattern (chdir tmp_path, monkeypatch
  `_config_cache`).
- Deps: B5–B8.
- Complexity: medium.
- Acceptance: ≥15 new tests, all 164+ tests green.

**E2. Update `.omh/README.md` and plugin README**
- Document the wrapper, the breadcrumb schema, the path layout, the
  recovery procedure.
- Deps: B5.
- Complexity: small.

**E3. Migration guide `.omh/research/ralplan-omh-delegate/migration.md`**
- Per-skill diff snippets.
- Deps: D1.
- Complexity: small.

### Suggested execution order (dependency-respecting)

1. A1, A2 in parallel → A3.
2. B1 (parallel with A track).
3. B2, B3, B4 in parallel (after A2 + B1).
4. B5 → B6, B7, B8 in parallel.
5. C1 in parallel with all of B; C2 after C1 + B5.
6. E1 after B5–B8; E2 in parallel.
7. D1 after B7 + E1; D2/D3/D4 in parallel after D1.
8. E3 after D1.

---

## 3. Open Design Questions — answered

> The spec lists Q1–Q5 and Q9–Q11 explicitly (Q6–Q8 implied gaps). I
> address all 11 below; for the gap-numbered questions I infer the most
> plausible intent from spec body text (atomicity, FM2 timeout, batch
> semantics) and answer those.

**Q1. One breadcrumb file per dispatch, or one rolling log?**
**Per-dispatch.** Path: `.omh/state/dispatched/{id}.json`. Reasoning:
atomic writes are trivial per-file (mirrors `omh_state`); concurrent batch
dispatches don't contend; GC is `find -mtime +N -delete`. A rolling log
requires append-safe writes (fcntl) and complicates atomicity. For
"scan history," ship a `omh_recover --list` helper that just `glob`s the
dir — cheap and only needed during recovery.

**Q2. Where do output files live?**
**`.omh/research/{mode}/`** (tracked). Reasoning: subagent outputs are
decision artifacts (planner reports, critic reviews, exec logs). They
have long-term value, are referenced by the final plan, and belong in
git. `.omh/state/` stays for ephemera (the breadcrumbs themselves and
in-flight mode state). This matches the just-landed convention.

**Q3. Second-call collision (same mode/phase)?**
**`overwrite="suffix"` default.** Append timestamp + 4-char random
disambiguator (already in the path template). Round number is part of
the path when supplied. Rationale: ralplan reruns the same phase across
rounds and reruns within a round (e.g., re-planner after critique) —
overwriting would erase prior evidence. We expose `overwrite="overwrite"`
for callers who explicitly want idempotency, and `overwrite="refuse"`
for paranoid one-shot dispatches. Suffix is the safe default because
"don't lose evidence" is the entire point of the wrapper.

**Q4. Strict signature vs loose passthrough?**
**Strict on `mode` and `phase`; loose on the rest via `**passthrough`.**
Reasoning: mode+phase are *the* primary keys for path computation and
breadcrumb lookup; without them the wrapper has no value. Everything
else can pass through to `delegate_task`. We do not enforce `role` or
`round` — `role` is a convenience for the breadcrumb, `round` is
ralplan-specific. Wrapper raises `ValueError` early if mode/phase
missing.

**Q5. session_id capture timing?**
**Capture post-completion only, in v1.** Track C1 documents this as a
research task; if Hermes exposes pre-dispatch session_id, we wire it,
but we do not block v1 on it. Recovery story (C2) works with
post-completion ID; FM2 (subagent never returns) means we may not get
the ID at all — mitigations there require a Hermes-side hook
(out of scope, tracked as RFE).

**Q6. (gap — atomicity scope)** — *Should atomic writes apply to
breadcrumb updates as well as initial dispatch?* **Yes, all writes use
`omh_io.atomic_write_text`.** Breadcrumb updates are read-modify-write:
load JSON, mutate, write tmp, fsync, replace. No partial breadcrumbs.

**Q7. (gap — FM2 timeout)** — *Should the wrapper itself enforce a
timeout?* **No, not in v1.** Killing a subagent mid-flight from outside
Hermes is unreliable and risks orphaned state. Track C3 records this as
an RFE for Hermes-core. The breadcrumb's `dispatched_at` plus a future
`omh_recover --stale --older-than 30m` gives operators a manual lever.

**Q8. (gap — batch semantics)** — *On batch, do we fail-fast or
fail-soft?* **Fail-soft.** Each task returns its own `ok` flag.
Aggregate `ok` is `all(r["ok"] for r in results)`. Batch is meant to
parallelize independent debate roles; one bad subagent shouldn't poison
the others.

**Q9. wrapper-persists vs subagent-persists — which?**
**Hybrid: subagent-persists primary, wrapper-persists fallback.** See §1
for full reasoning. Edge cases addressed:
- *Path drift* (subagent writes elsewhere): wrapper detects on verify;
  if returned content is substantive, wrapper writes to expected path
  and records the drift in breadcrumb.
- *Skill-prose burden*: minimized by goal-injection — skill author writes
  `omh_delegate(mode=..., phase=...)` and the wrapper appends the
  `<<<EXPECTED_OUTPUT_PATH>>>` block. Skill prose only needs to know
  "use omh_delegate, not delegate_task."
- *Is the wrapper still needed?* Yes: deterministic path computation,
  breadcrumb lifecycle, verification, and the recovery branch all need
  code, not prose. Pure-prose works only in degraded mode (see Q11).

**Q10. Steered-debate mode** — Out of scope for `omh_delegate` v1.
Tracked as separate RFE `.omh/research/rfe-steered-ralplan.md`. Note:
the breadcrumb + research-file layout makes steering *trivial* later —
a steering loop just reads the latest breadcrumb, surfaces
`expected_output_path`, and waits for human ack before dispatching the
next phase. So this design enables steering without designing for it.

**Q11. Migration path?**
**Per-skill, with a graceful shim.** Sequence:
1. Land plugin tool (Tracks A+B+E1).
2. Migrate ralplan first (D1) — highest-value, the dogfood case.
3. Migrate ralph, autopilot in parallel (D2/D3) once ralplan proves the
   pattern.
4. Shim behavior: if `omh_delegate` is unavailable at skill runtime,
   skills SHOULD include a prose fallback ("call delegate_task and
   immediately write_file the result yourself"). The wrapper itself
   degrades to passthrough if its breadcrumb dir is unwritable (B8).
5. We do *not* monkeypatch `delegate_task`; coexistence is explicit.

**Bootstrap recursion (acceptance criterion):** ralplan-on-omh_delegate
runs *today* using plain `delegate_task` (current state). Once D1 lands,
ralplan-on-self uses `omh_delegate` for all future dispatches. The
artifacts produced by *this* ralplan run live at
`.omh/research/ralplan-omh-delegate/` regardless — the orchestrator is
manually persisting (belt-and-suspenders) so the design conversation
itself isn't lost. This is the bootstrap: prose-level subagent-persists
for the round that designs the wrapper; tool-level for everything after.

---

## 4. Risks

- **R1. Path drift despite injection.** Subagents may "improve" the path
  (trim trailing slashes, change extension, rewrite the timestamp).
  Mitigated by the wrapper's recovery branch (writes returned content to
  the *expected* path regardless), but if the subagent both writes
  elsewhere *and* returns no content, we lose. Mitigation: contract
  text is brutal and explicit; we add a regex check that flags drift in
  the breadcrumb.

- **R2. `delegate_task` return shape unknown / varies.** The plan
  assumes the return is either a string (the path) or a dict containing
  a path/content field. We need to confirm against current Hermes.
  Track C1 doubles as this audit. Risk: parsing fragility. Mitigation:
  generous extractor with fallbacks; raw return always preserved in
  result.

- **R3. Breadcrumb dir GC.** Long-running projects accumulate
  breadcrumbs. Not a correctness risk; UX risk. Mitigation: ship
  `omh_recover --gc --older-than 14d` in C2, document.

- **R4. Skill prose drift.** If skill authors call `delegate_task`
  directly going forward, they bypass the wrapper. Mitigation: lint /
  CI grep for `delegate_task(` in `plugins/omh/skills/` after migration
  D1–D4; allowlist documented exceptions.

- **R5. Dogfood deadlock.** This very ralplan run depends on subagent
  outputs being persisted. Mitigation already in flight: orchestrator
  persists to `.omh/research/ralplan-omh-delegate/` immediately on
  receipt (this file is exhibit A).

- **R6. Plugin import order / Hermes plugin contract.** New tool
  registration must not break existing 164 tests or Hermes startup.
  Mitigation: incremental land (A1/A2 first; B7 last), full test run
  between each.

- **R7. Atomicity on networked / quirky filesystems.** `os.replace` is
  atomic on POSIX same-fs; cross-fs or fuse mounts can fail. Mitigation:
  document `.omh/` should be on local fs; `omh_io.atomic_write_text`
  raises a clear error on cross-device replace.

---

## 5. Open Questions (need answers before / during execution)

- **OQ1.** What does `delegate_task` actually return in current Hermes?
  Single-task and batch shapes both. (Blocks B5/B6 detail; resolve in
  C1.)
- **OQ2.** Does `delegate_task` expose `session_id` pre-completion via
  any callback or context-manager API? (Blocks FM2 mitigation quality;
  resolve in C1.)
- **OQ3.** Is there a Hermes-supported way to discover the project root
  besides `omh_config["project_root"]`? (Affects A2 robustness when OMH
  config is absent — does wrapper still work?)
- **OQ4.** Should `return_content=True` be the default for the
  ralplan/ralph use cases? (Convenience vs hand-up size tradeoff. Lean
  False for now; revisit after D1.)
- **OQ5.** Acceptable max breadcrumb size? Goal previews could be large.
  Propose 240-char preview + `context_bytes` count. Confirm with
  Architect.
- **OQ6.** Naming: `omh_delegate` vs `omh_dispatch`? Spec uses
  `omh_delegate`; keeping it, but flagging for Critic.

---

## 6. Out-of-Scope (explicit)

- Modifying Hermes core `delegate_task`.
- Heartbeats / partial-output streaming from subagents.
- Replacing `delegate_task` for non-OMH callers.
- Steered-debate UX (Q10) — separate RFE.
- Cross-machine breadcrumbs / distributed recovery.
- Encryption / redaction of breadcrumb content (callers must avoid
  putting secrets in `goal`).

---

## 7. Acceptance Criteria roll-up (mapped to spec §"Acceptance Criteria")

- [x] Exact tool signature → §B1.
- [x] Exact file layout under `.omh/` → Q2 + B2 + A3.
- [x] Breadcrumb schema → B3.
- [x] All open design questions addressed → §3 (Q1–Q11).
- [x] Migration plan for ralplan, ralph, autopilot → Track D.
- [x] Test strategy (atomicity, recovery, batch) → E1 + per-task
      acceptance criteria.
- [x] Plugin-unavailable behavior → B8 + Q11.
- [x] Recursive ralplan bootstrap addressed → Q11 closing paragraph.

---

*End of Round 1 Planner output.*
