# Round 2 — Architect Review: omh_delegate Plan (Reconciled)

**Role:** Architect
**Reviewing:** round2-planner.md
**Date:** 2026-04-20

---

## 1. Verdict

**APPROVE.**

Round 1's three Architect concerns landed cleanly and unambiguously:
- C1 (append-only breadcrumb events) — mandated, not "leaning toward."
  `{id}.dispatched.json` + `{id}.completed.json` (+ `.recovered.json` in
  v1.B). RMW eliminated. Schema explicitly tags `_meta.kind` so a glob
  reader can compose the lifecycle deterministically.
- C3 (split A3) — accepted; v0 inlines the mkdir at the call site,
  shared-module work (A2) deferred to v1 where it pays down real
  duplication across `omh_state` / `evidence_tool` / `omh_delegate`.
- C5 (three-boolean status) — mandated and threaded through the v0
  schema even though `recovered_by_wrapper` is permanently `False` and
  `contract_satisfied == file_present` for the entire v0 lifetime. That
  is the right call: the schema is the contract that has to survive
  v1.B, and burning the booleans into v0 means no migration when the
  rescue path lights up.

C2 (OQ1 as a B5 blocker) is moot under v0 since v0 does not parse the
return; OQ1 correctly reactivates as a v1.B precondition. C4
(classifier decision table) is rejected in form but accepted in spirit:
v1.B's marker-present/marker-absent binary is *better* than my Round 1
five-class table because it removes the `looks_like_path` heuristic
entirely, which the Critic was right to call out as adversarial-fragile.
I withdraw my C4 form.

The v0/v1/v2 phasing is sound. Boundaries are clean. The schema is
forward-stable. I would ship this.

---

## 2. Strengths

- **Schema stability across phases is the headline win.** The v0
  breadcrumb schema is identical in shape to what v1.B will need; only
  the *values* of `contract_satisfied` and `recovered_by_wrapper`
  change behavior. No reader code needs to migrate. `_meta.schema_version=1`
  + `_meta.kind` gives the version handle if v2 needs to evolve.
- **Append-only events compose with `atomic_write_text` trivially.** No
  RMW anywhere in v0. The `dispatched`/`completed`/`recovered` triple is
  also the natural shape for a future `list_dispatches` reader (M2,
  deferred to v2 with the recovery CLI — correct deferral).
- **v0 surface is genuinely minimal.** ~80 LOC, 3 tests, one migrated
  skill phase. The dogfood loop is the measurement instrument for v1's
  decision rule. This is a research-grade ship: hypothesis, instrument,
  decision criterion, all pre-registered.
- **Rescue-branch deferral is structurally clean, not just scope-cut.**
  v0 has no classifier, no parsing, no second codepath. The only
  observable is "did the file land?" That is the smallest possible
  honest interface. v1.B's optional rescue is additive: a new event
  file kind (`recovered.json`), a new tri-state value for `ok`, a new
  derived `ok_strict` field. Nothing in v0 has to change shape.
- **Project-root discovery via `.omh/` walk-up (W4) is the right
  boundary.** Mirrors `git`'s `.git` discovery, removes the OMH-config
  dependency I flagged in M7, and is 5 lines. Strictly better than my
  Round 1 suggestion.
- **Goal preview replaced by `goal_sha256` + `goal_bytes`** (W2) — also
  strictly better. Hash + length is enough to detect identity and size
  drift without storing prompt bytes that may carry secrets.
- **No silent degrade** (W3). Unwritable `.omh/` raises. Good.
  Eliminates the third codepath I was nervous about without naming.

---

## 3. Concerns

None blocking. The items below are notes I would carry into v1, not
blockers for v0 ship.

### N1. v0 inline duplication of atomic_write_text + project-root discovery.

The plan acknowledges this and resolves it in v1.A1/A2. The duplication
is ~15 LOC for one PR's lifetime. That is acceptable: the alternative
(land `omh_io.py` in v0 and refactor `omh_state` + `evidence_tool` in
the same PR) doubles v0's blast radius and delays the C0 measurement,
which is the actual point of v0. **Take the duplication, pay it down in
v1.A.** The migration friction is one global-replace and a deletion of
the inline copies; not real friction.

### N2. `contract_satisfied` as a permanently-`== file_present` field in v0.

This is the question the parent flagged. My answer: **it is
forward-compatible, not tech debt.** The field's *semantics* are stable
across phases ("did the subagent honor the contract by writing the
file itself, vs the wrapper having to rescue it?"). In v0 those two
notions collapse because there is no rescue path; in v1.B they
diverge. A reader that checks `contract_satisfied` in v0 and again in
v1.B gets the right answer in both worlds with no code change.

The alternative — omit `contract_satisfied` from v0 and add it later —
forces every v0 reader to gain a defensive `.get('contract_satisfied',
result['file_present'])` fallback when v1.B ships. That is the actual
debt. Ship the field now.

### N3. OQ-A through OQ-E classification — operational vs structural.

- OQ-A (C0 methodology — what counts as "obeyed"): **operational.**
  Doesn't lock the design.
- OQ-B (C0 sample composition): **operational.** Methodology only.
- OQ-C (v1.B threshold 95/80%): **structural-ish but pre-locked.** The
  planner correctly notes this should be set *before* C0 runs to avoid
  motivated reasoning, and locks it in §6. That is the responsible
  move; see N5 below.
- OQ-D (`.omh/` walk-up under Hermes cwd): **structural.** If Hermes
  chdirs unexpectedly mid-session, the walk-up resolves to the wrong
  root and breadcrumbs scatter. This is worth verifying during v0
  implementation, not after. Mitigation is trivial (snapshot project
  root at first call, cache for process lifetime), but it should be
  consciously done. Flag for v0 implementation.
- OQ-E (orphaned dispatched.json on Hermes restart): **structural in
  spirit, operational in v0.** v0 documents the orphan as the
  reconstruction signal, which is the correct semantics. v2 recovery
  CLI formalizes cleanup. No design lock-in either way; the schema
  already supports it.

So: OQ-D is the only one I'd elevate. The rest are correctly scoped.

### N4. `ok` bool → tri-state migration via `ok_strict`.

The parent asked whether `ok_strict` is a clean migration path or a
smell. **It's a clean path, with one caveat.** v0 callers writing
`if result['ok']:` will keep working in v1.B for the happy path and
will (correctly) evaluate the `"degraded"` string as truthy — which is
*wrong* for callers that wanted strict pass/fail. `ok_strict` exists
exactly for those callers, and the v1.B release notes need to call out
"audit your `if result['ok']` sites; switch to `ok_strict` if you want
hard pass/fail."

The smell would be if `ok` *silently* changed type with no escape
hatch. It doesn't — `ok_strict` is the escape hatch and the field name
is self-documenting. Acceptable. (If we wanted belt-and-suspenders, v0
could ship `ok_strict` *now* as `== ok` so callers can migrate
preemptively. Cheap. Worth doing.)

### N5. Threshold rule (≥95 / 80–95 / <80) committed before data exists.

The parent asked: responsible or premature? **Responsible.** Locking the
decision rule before the measurement is the textbook way to avoid
post-hoc rationalization of whichever number comes back. The thresholds
themselves are defensible: ≥95% means rescue would be dead code in 19
of 20 dispatches (build cost > expected benefit); <80% means the
contract itself is broken and code can't fix prose. The 80–95% middle
band is the only ambiguous regime and that's where rescue earns its
keep.

The one risk: if C0 returns, say, 92% on n=20, that's a single dispatch
of slack from the 95% line. The plan should commit to "if measured
rate's lower 95% CI crosses the threshold, treat as the worse band."
Trivial to add to `c0-contract-obedience.md`. Not blocking.

---

## 4. Missing

- **M1'. OQ-D resolution should be a v0 implementation checklist item,
  not just an open question.** Snapshot project root at module-load or
  first-call time; document the cache. Five lines.
- **M2'. Ship `ok_strict` in v0** (per N4). Lets v0 callers preemptively
  adopt the strict-check shape so v1.B is a no-op for them.
- **M3'. `c0-contract-obedience.md` template should exist before v0
  ships.** The plan describes what goes in it; pre-create the skeleton
  with the locked thresholds and the classification taxonomy so the
  measurement is mechanical and not a fresh design exercise after the
  dispatches are in hand.

None of these block v0.

---

## 5. Verdict on the parent's specific structural questions

- **v0 inlines what v1.A1/A2 will extract — acceptable for one PR?**
  Yes. ~15 LOC, well-bounded, paid down in v1.A1+A2. Migration is
  mechanical. Ship the duplication.
- **`contract_satisfied` as a constant-in-v0 field — forward-compatible
  or debt?** Forward-compatible. The semantics are stable; only the
  values converge in v0. Omitting it would create real defensive-code
  debt in every reader when v1.B ships.
- **OQ-A/B/C/D/E — structural or operational?** A/B are operational.
  C is structural-but-pre-locked (correctly). D is the one truly
  structural item; should be resolved in v0 implementation. E is
  operationally documented in v0 and formalized in v2.
- **`ok` bool → tri-state via `ok_strict` — clean or smell?** Clean,
  with the caveat that `ok_strict` should ship in v0 too so callers can
  migrate before v1.B forces them to.
- **C0 threshold rule pre-committed — responsible or premature?**
  Responsible. Pre-registration is correct methodology. Add a CI rule
  for borderline outcomes.

---

## 6. Closing

Round 1's structural concerns are addressed. The schema is honest, the
phasing is disciplined, the rescue branch is correctly conditional on
evidence, and the v0 surface is small enough that the C0 measurement
will return useful data fast. The remaining notes (N1–N5, M1'–M3') are
v1-track refinements, not v0 blockers.

Ship v0.

**APPROVE.**

---

*End of Round 2 Architect review.*
