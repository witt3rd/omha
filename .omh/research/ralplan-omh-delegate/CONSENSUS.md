# omh_delegate — ralplan Consensus

**Date:** 2026-04-20
**Subject:** `omh_delegate` — hardened wrapper around `delegate_task`
**Mode:** ralplan (3-role debate, 2 rounds)
**Outcome:** CONSENSUS REACHED

---

## Verdict trail

| Round | Planner       | Architect          | Critic                              |
|-------|---------------|--------------------|-------------------------------------|
| R1    | (proposed)    | REQUEST_CHANGES    | REQUEST_CHANGES (aggressive)        |
| R2    | (reconciled)  | **APPROVE**        | **APPROVE with conditions**         |

Three APPROVE → debate converges on the Round 2 plan.

---

## Authoritative plan

`round2-planner.md` is the ship-ready plan. Read it for full task list, schemas,
test list, and v0/v1/v2 phasing.

Headline:

- **v0** = single file `plugins/omh/omh_delegate.py` (~80 LOC) + 3 tests +
  one migrated `omh-ralplan` planner-phase. Ships in one PR, ~1 day.
- **No rescue branch in v0.** Pure subagent-persists. `file_present=False`
  surfaces loudly (stderr warning, `ok=False`, raw return preserved on
  completion breadcrumb).
- **C0 microbenchmark** (≥20 real dispatches) gates v1 shape. Pre-locked
  thresholds: ≥95% obedience → no rescue ever; 80–95% → loud-only rescue
  in v1.B; <80% → fix prose, not code.
- **Mandated from day one** (Architect-required structural fixes):
  - Append-only breadcrumb events (`{id}.dispatched.json`,
    `{id}.completed.json`, optional `.recovered.json`). No RMW.
  - Three-boolean status (`file_present` / `contract_satisfied` /
    `recovered_by_wrapper`). `verified` retired.
  - Atomic writes (tmp → fsync → `os.replace`).
  - `goal_sha256` + `goal_bytes` only — no goal preview (W2 secrets).
- **`.omh/` walk-up** for project-root discovery (mirrors `git`).
- **No silent degrade** when `.omh/` is unwritable — raise.

---

## Approval Conditions (doc-only, MUST land with v0)

### AC-1 (Critic). Flag `ok="degraded"` truthy hazard.

When v1.B reintroduces the rescue branch, `ok` becomes tri-state
(`True` | `False` | `"degraded"`). Python truthiness will treat
`"degraded"` as truthy in idiomatic `if result["ok"]:` checks. A naïve
caller will treat a degraded result as success.

**Required action in v0 docs and the v0 wrapper docstring:** explicitly
document the future migration. Recommend (and ship in v0) the
`ok_strict = (ok is True)` derived field so callers can write
`if result["ok_strict"]:` and remain correct across the v0→v1.B
transition. Architect's "ship `ok_strict` in v0 too" note is folded
into this AC.

### AC-2 (Critic). README note on cross-fs `os.replace`.

W6 (cross-fs `os.replace` failure on FUSE / Docker volume mounts) is
deferred to v2. v0 must document this in the plugin README so the
deferral is *intentional and discoverable*, not silently inherited.
One paragraph naming the failure mode and the v2 mitigation.

---

## Architect's non-blocking notes (advisory, not gating)

- **N1.** Inline duplication in v0 (atomic_write_text, project-root
  discovery) is acceptable for one PR's lifetime. v1.A1/A2 extracts
  them properly.
- **N2.** **OQ-D is the one structurally load-bearing OQ** — does Hermes
  `chdir()` during dispatch, breaking `.omh/` walk-up? Resolve during
  v0 implementation, not after. If Hermes does chdir, project-root
  must be captured at the call site (before dispatch), not at any
  later point.
- **N3.** Pre-locked C0 thresholds (95% / 80%) are responsible — they
  prevent motivated reasoning when ambiguous data lands.
- **N4 (folded into AC-1).** Ship `ok_strict` in v0 too.

## Critic's residual warnings (advisory)

- **W-R2-1.** Per-role / per-failure-mode breakdown in C0. Don't just
  measure aggregate obedience; bin by role (planner / architect /
  critic) and failure mode (drift / double-write / refusal /
  paraphrase / acknowledgment / other). A 92% aggregate that hides a
  60% obedience rate from one role is a different story than a clean
  92% across all roles.
- **W-R2-2.** R8 (C0 inconclusive) — be willing to extend the dogfood
  window rather than ship v1.B speculatively.
- **W-R2-3.** R9 (three-state ok) — see AC-1.
- **W-R2-4.** Document v2-deferred items (W1 concurrency, W6 cross-fs)
  in the plugin README so the deferrals are explicit.

---

## Suggested execution

1. **v0 implementation.** Implement per `round2-planner.md` §3 + AC-1
   (`ok_strict` field) + AC-2 (README cross-fs note). Resolve N2/OQ-D
   during implementation.
2. **v0 dogfood.** Migrate one `omh-ralplan` phase, run ≥20 dispatches
   against ≥3 toy specs, write per-role/per-failure-mode tally to
   `c0-contract-obedience.md`.
3. **v1 shape decision.** Apply C0 threshold rule. Document the
   decision and reasoning in
   `.omh/research/ralplan-omh-delegate/v1-decision.md`.
4. **v1.A always.** A1/A2 extraction, B6 batch, B7 tool registration,
   D2/D3/D4 skill migrations, E1/E2/E3 docs+tests.
5. **v1.B conditional.** Only if C0 said 80–95%: rescue branch in
   loud-only sentinel form.
6. **v2 on demand.** session_id capture, recovery CLI, GC, lock
   sentinel, cross-fs detection, steered debate.

---

## Artifact index

- `00-spec.md` — original spec
- `round1-planner.md` — Round 1 maximalist plan
- `round1-architect.md` — Architect REQUEST_CHANGES (C1–C5, M1–M7)
- `round1-critic.md` — Critic REQUEST_CHANGES (CI-1–CI-5, W1–W6)
- `round2-planner.md` — reconciled plan (the ship-ready one)
- `round2-architect.md` — Architect APPROVE (with N1–N4 notes)
- `round2-critic.md` — Critic APPROVE (AC-1, AC-2, W-R2-1..4)
- `CONSENSUS.md` — this file

---

*ralplan converged 2026-04-20. Ready to execute v0.*
