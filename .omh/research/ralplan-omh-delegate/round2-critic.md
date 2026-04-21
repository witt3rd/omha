# Round 2 — Critic: omh_delegate Reconciled Plan

**Role:** Critic (adversarial)
**Reviewing:** round2-planner.md against round1-critic.md
**Date:** 2026-04-20

---

## 1. Verdict

**APPROVE — with warnings and two approval conditions.**

The Round 2 Planner accepted CI-1 through CI-5 substantively, not
cosmetically. v0 is a one-file, three-test, ~80 LOC ship that exists
specifically to generate the C0 measurement before any rescue-branch
decision is made. The reframing in §2 ("the wrapper automates an
already-working pattern; it does not enable it") is the honest version
of CI-3, and it is now load-bearing for the rest of the doc rather
than buried.

The residual disagreements (rescue-branch-in-reserve, deferred W1/W6,
pre-locked OQ-C thresholds, `ok="degraded"` string in v1.B) are
real but proportionate. None of them rise to REQUEST_CHANGES given
that v1.B is gated, conditional, and does not exist until evidence
demands it. Manufacturing a third round of objections at this point
would be theater.

This is convergence. Three APPROVE verdicts incoming.

---

## 2. Stress-test of the Planner's residual choices

### 2.1 Is "rescue-branch-in-reserve" a soft-version of the CI-1 problem?

Partially yes, mostly no.

The Planner kept v1.B (loud-form rescue) as a *conditional* that fires
only if 80% ≤ obedience < 95%. That is materially different from
Round 1's unconditional fallback for three reasons:

  1. v0 ships without it, so the feedback loop CI-1 cared about
     (orchestrator notices contract drift, fixes prose) is preserved
     during the period when prose is most likely to be wrong.
  2. The rescue, if it ever ships, is sentinel-marker-gated (CI-5
     accepted) and emits `ok="degraded"` + in-band header + stderr —
     which is CI-1 option (b), the form I explicitly said was
     "acceptable but more code."
  3. There is a documented exit ramp (≥95% → v1.C, rescue never
     ships).

The residual CI-1 concern: even loud-form rescue still saves the
bytes. Once the bytes are saved, the orchestrator's pressure to fix
the prose drops from "must" to "should." That is a softer version of
the same problem. But it is no longer the dominant failure mode —
a `degraded` status string and a stderr line are hard to ignore in
an interactive orchestration loop. Acceptable.

### 2.2 Is `ok="degraded"` (string) worse than the bool→tri-state disease it cures?

This is the choice I am least happy with, but it is defensible.

Pros: callers that branch on `if result["ok"]:` will get truthy for
`"degraded"` (non-empty string is truthy in Python), so they will treat
degraded as success — which is exactly the failure mode CI-1 warned
against. **This is a real bug surface.**

The Planner partially mitigates with `ok_strict = (ok is True)` in R9.
That is a workaround, not a fix. Callers must remember to use it.

Better alternative the Planner should consider before v1.B lands:
make `ok` strictly `bool` and add a separate `status` enum field
(`"clean" | "degraded" | "failed"`). Truthy-checks on `ok` then
correctly fail-closed for degraded. Document loudly that callers must
read `status` not `ok` to distinguish clean from rescued.

I am flagging this as **Warning W-R2-1** rather than a CI because v1.B
is conditional and may never ship; if it does, the fix is one field
rename.

### 2.3 Are W1 (concurrency) and W6 (cross-fs) safe to defer?

W1 (multi-orchestrator / Hermes background) — **safe to defer.** v0
explicitly states single-orchestrator as an assumption, the breadcrumb
schema is append-only (so the worst case of a collision is two
orphaned dispatched.json files with different IDs, not corruption),
and the random suffix in `id` makes filename collision astronomically
unlikely. A `.lock` PID sentinel before any real bug report would be
gold-plating.

W6 (cross-fs `os.replace`) — **mostly safe, watch for it.** The
Planner punts to "raise a clear error with paths and a hint." That
covers detection. The landmine: dev-container users on FUSE-mounted
`.omh/` may hit this on their first dispatch and have no idea what
the error means. One sentence in the v0 README ("if you see
`OSError: Invalid cross-device link`, your `.omh/` straddles a mount
boundary; move it onto the same filesystem as `/tmp` or set
`OMH_TMPDIR` to a sibling") would close the operability gap for ~$0.
**Approval Condition AC-2 below.**

### 2.4 Does pre-locking OQ-C thresholds prevent motivated reasoning, or create rigidity?

Both, and the trade is correct.

Locking 95% / 80% before C0 runs is the Tetlock move: pre-register
the decision rule so post-hoc rationalization is harder. The risk is
ambiguity at the boundary — what if C0 measures 94.5% on n=20? The
Planner's R8 already covers the "inconclusive" case (extend dogfood
window). The bigger gap: **no rule for what happens if C0 produces
something weird**, e.g., 100% obedience but all six failures concentrate
in one role, or obedience is high but content quality is low.

Suggestion (not a blocker): add to OQ-A that the C0 writeup must
include a per-role breakdown and a qualitative failure-mode bin, so
a 94% headline number with all 6% failures concentrated in one skill
triggers prose-fix work on *that skill* rather than a global v1.B
decision. The threshold is a default; the writeup should permit
informed override with explicit reasoning. Captured as Warning
W-R2-2.

### 2.5 Does v0 actually answer "is the wrapper worth building?" or only "how big should v1 be?"

Honest answer: only the latter.

v0 ships the wrapper. By shipping it, the question "is the wrapper
worth building" is implicitly answered yes-on-ergonomics-grounds, per
the Planner's §2 reframe. v0 then measures contract obedience to size
v1, not to validate v0 itself.

Is that a problem? No. The reframe in §2 is the actual answer to "is
the wrapper worth building": it is worth building because skill prose
is currently hand-rolling timestamps, breadcrumbs, and verification,
and the wrapper centralizes that. The bootstrap proves the *pattern*
works in prose; the wrapper *automates* the pattern. The two
questions ("is the pattern correct?" and "should the pattern be
automated?") are separable, and the Planner separated them cleanly.

What v0 does *not* do that I would still like to see: a one-line
honest answer to "if C0 says 100% and v1.A ships and we never write
v1.B, what was the point of the schema fields `contract_satisfied`
and `recovered_by_wrapper`?" Answer: schema stability across the
v0/v1/v2 transition, even when two of three booleans are constants in
v0. The Planner's §1 alludes to this; making it explicit in §3
("schema is forward-compatible with v1.B even if v1.B never ships")
would close the loop. Minor.

### 2.6 New concern surfaced by the Round 2 reframing

One. The reframe says "the wrapper is operational ergonomics, not
correctness." If that is literally true, then **the wrapper is
optional from a correctness standpoint**, which means skills that
have not yet migrated are not broken — they are just verbose. That
is fine for migration ordering (low-pressure, do it as touched), but
it has an implication the Planner did not state: **D2/D3/D4
migrations are no longer the load-bearing work.** They are
opportunistic.

This deserves one sentence in v1.A: "skill migrations are
ergonomic, not corrective; un-migrated skills continue to work
via prose-level subagent-persists." Otherwise reviewers will
read v1.A and assume D2/D3/D4 are blocking when they are not.
Captured as Warning W-R2-3.

---

## 3. Warnings (do not block approval)

- **W-R2-1.** v1.B's `ok="degraded"` (string in a bool-typed field)
  is a truthy-check footgun. If v1.B ships, prefer strict `ok: bool`
  + separate `status: enum`. The `ok_strict` derived field in R9 is
  a partial mitigation, not a fix.
- **W-R2-2.** OQ-C thresholds are pre-locked, which is good, but
  the C0 writeup should include per-role and per-failure-mode
  breakdowns so a high headline rate doesn't mask a bad subset.
- **W-R2-3.** State explicitly in v1.A that skill migrations are
  ergonomic, not corrective, so reviewers don't read D2/D3/D4 as
  blocking.
- **W-R2-4.** The schema-stability rationale for shipping all three
  booleans in v0 (where two are trivially constant) is alluded to but
  not stated. One sentence in §3 would close it.

---

## 4. Approval Conditions

The plan is APPROVED if these two trivial additions are made before
v0 implementation begins. Both are documentation-only.

- **AC-1.** Add one sentence to v1.B's spec stating the truthy-check
  hazard of `ok="degraded"` and committing to revisit the field
  shape (W-R2-1) before v1.B implementation begins. This is not a
  redesign demand; it is a "don't ship the field shape without
  reconsidering it" note.
- **AC-2.** Add one line to the v0 README / migration doc explaining
  the cross-fs `os.replace` failure mode and the workaround, so v0's
  W6 deferral does not become a first-touch operability landmine.

These are strictly optional in the sense that the plan is sound
without them; they would close the only two residual concerns I have
left after Round 2.

---

## 5. What converged

CI-1, CI-2, CI-3, CI-4, CI-5: all accepted in substance. The Planner's
pushbacks on "delete rescue forever" and "wrapper is gilding" are
honest, narrowly-scoped, and properly constrained by C0 evidence and
the reframe respectively. I disagree with neither.

Architect's C1 (append-only events) and C5 (three-boolean status):
both mandated. W2/W3/W4/W5 from my Round 1: all accepted in v0 form.
W1 and W6: deferred with documented assumptions, which is the
correct level of effort for v0.

The plan's §8 ("scope cut by ~70%") is a fair self-assessment. v0
is now the smallest version that ships, exercises the contract,
generates C0 data, and preserves schema-forward-compat to v1/v2. That
is exactly what I asked for in Round 1 §5.

---

## 6. One last honest note

The point of an adversarial round is to *converge when convergence is
real*. The Round 2 Planner did the work: accepted the substantive
critique, pushed back where pushback was earned, and produced a plan
that is materially better than Round 1 along every axis I attacked.
Refusing to APPROVE here would be performative rigor at the cost of
actual progress.

Three APPROVE verdicts. Ship v0. Run C0. Decide v1 from data.

---

*End of Round 2 Critic review.*
