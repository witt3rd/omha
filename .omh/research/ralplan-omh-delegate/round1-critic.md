# Round 1 — Critic: omh_delegate Plan + Architect Review

**Role:** Critic (adversarial)
**Reviewing:** round1-planner.md AND round1-architect.md
**Date:** 2026-04-20

---

## 1. Verdict

**REQUEST_CHANGES** — and more aggressively than the Architect did.

The Planner's plan is competent and the Architect's review is sharp on the
points it covers. But both share a blind spot: they have already *agreed*
that the hybrid (subagent-persists primary + wrapper-persists fallback) is
the right shape, and from there the conversation has only refined how to
build it. Nobody in the room has seriously argued for cutting the wrapper
in half, deleting the fallback branch, or shipping a 50-line v0. I am
that voice.

There is also a load-bearing empirical question both documents tiptoe
around: **does the brutal-prose contract actually work on real subagents,
or are we designing recovery machinery for a contract we haven't
measured?** The whole hybrid leans on this and neither doc has data.

The plan as written will probably ship and probably work. But it is
roughly 2-3x bigger than it needs to be for v1, and the parts that are
extra are also the parts most likely to mask the very bug they are trying
to fix.

---

## 2. Critical Issues (must address)

### CI-1. The wrapper-persists fallback is a footgun, not insurance.

**Issue.** Steel-manning the inversion the parent flagged: the Planner
argues the fallback is "5 lines, nearly free." That is the cost in code.
The cost in *signal* is much higher.

When the subagent violates the contract (returns prose instead of writing
the file), the wrapper silently rescues it, marks `verified=true`, and
hands the caller a file that *looks* like a properly-persisted artifact.
`recovered_by_wrapper=true` is a flag in a JSON file nobody reads unless
something else has already gone wrong. The orchestrator will not stop and
fix the contract prose, because from its vantage point everything worked.

This is exactly the dynamic that produces the bug class
the wrapper exists to prevent: invisible degradation. FM1 was invisible
("subagent returned, parent dropped it"); the fallback creates a new
invisible failure ("subagent ignored contract, wrapper papered over it,
artifact is the raw chat preamble"). The Architect's C5 noticed the
*content quality* version of this (saving garbage as if it were good),
but missed the *systemic* version: the fallback removes the feedback
loop that would teach us to fix the contract.

Without the fallback, contract violation is loud: `verified=false`, no
file, the orchestrator either retries with stronger prose or surfaces
the failure to the human. The bug gets fixed at the prose layer, where
it belongs. With the fallback, the prose stays sloppy forever because
the rescue branch always saves the day.

**Impact.** The plan optimizes for the worst case (subagent ignores
contract) at the cost of degrading the common case (subagent obeys
contract, and we never notice when it stops). Over time the contract
prose calcifies at "good enough to *usually* work" because there is no
pressure to make it better.

**Suggested fix.** Either:
  (a) **Drop the fallback in v1.** Ship pure subagent-persists.
      `verified=false` returns `ok=false` with a clear error and the raw
      payload preserved on the breadcrumb (NOT at expected_path). Force
      the orchestrator to either retry or escalate. Add the fallback
      later if and only if measurement shows the contract is unfixable
      at the prose layer.
  (b) **Keep the fallback but make it loud.** `recovered_by_wrapper=true`
      MUST surface as `ok="degraded"` (not `ok=true`), the rescued file
      MUST carry an in-band header (`<!-- CONTRACT VIOLATED -->` per
      Architect C5, but mandatory not optional), and the orchestrator
      SHOULD treat `degraded` as a soft failure that triggers a retry
      with hardened prose.

I lean strongly toward (a) for v1. (b) is acceptable but more code.

### CI-2. The brutal-prose contract is unvalidated.

**Issue.** The entire hybrid hangs on subagents *mostly* obeying
"<<<EXPECTED_OUTPUT_PATH>>>… your final action MUST be write_file at this
exact path." Neither plan nor review presents evidence that this works.
Subagents are LLMs. Predictable failure modes:
  - Path paraphrase (Planner R1 admits this).
  - Extension swap (`.md` → `.markdown`).
  - "Helpful" reformatting of the path (URL-encode, expand `~`,
    dequote).
  - **Double-write**: write_file the artifact AND return the content
    inline ("here's what I wrote so you can see it"). The classifier
    in Architect C4 cannot distinguish this from contract violation.
  - Wrap path in code fences in the return string.
  - Write the file but return a *summary* of the file rather than the
    path (because that's more "helpful").
  - Refuse the contract entirely if the goal text contains anything the
    safety layer dislikes.

This very task — me, a subagent, right now — was instructed via a
brutal-prose contract identical in spirit to the proposed one. The
parent has no way to know whether I obeyed until it checks. That is the
point of the wrapper. But the *design* of the wrapper assumes the
contract is mostly obeyed. We need numbers.

**Impact.** If contract obedience is, say, 70%, the fallback runs 30%
of the time and CI-1 bites hard. If it is 99%, the fallback is dead
code and we should delete it (CI-1 fix (a)). Without measurement, we
are guessing which regime we are in.

**Suggested fix.** Before B5/B6 land, run a **contract-obedience
microbenchmark**: dispatch 20 trivial tasks via plain `delegate_task`
with the proposed `<<<…>>>` block, count how many produce the exact
file at the exact path on the first try. Bin failures by mode (drift,
double-write, refusal, paraphrase). This is one afternoon of work and
it determines the entire shape of v1. Add as task **C0** (precedes
B5).

### CI-3. The bootstrap evidence cuts the *opposite* way from how the plan reads it.

**Issue.** The Planner cites the current ralplan-on-omh_delegate run
(this very session) as proof that the wrapper is needed: the orchestrator
is "manually persisting" subagent outputs. The Architect agrees:
"prose-level subagent-persists, post-D1 tool-level."

But re-read what is actually happening. The orchestrator (Forge) is
dispatching subagents with brutal-prose contracts ("your final action
MUST be `write_file('/abs/path', …)` and your return value MUST be
exactly the path") and the subagents are *obeying*. The artifacts are
landing at deterministic paths under
`.omh/research/ralplan-omh-delegate/`. There is no Python wrapper.
There is no breadcrumb file. There is no recovery branch. **It is
working.**

If the bootstrap is exhibit A for anything, it is exhibit A for "prose
+ discipline is sufficient, the wrapper is gilding." The plan reads it
backwards: the success of the prose-level pattern in the bootstrap is
evidence *against* the wrapper's necessity, not for it. At minimum, it
is evidence that the contract-obedience rate (CI-2) in this regime is
high enough that the fallback may never fire.

**Impact.** The plan's premise — "prose alone is degraded mode" (Q11) —
is contradicted by its own existence proof. Either the premise is
wrong, or the bootstrap is succeeding by accident and we should be
nervous. Both interpretations argue for shrinking v1 and measuring
before building.

**Suggested fix.** Add an honest §1 paragraph: "The bootstrap of this
ralplan run is itself a successful prose-only subagent-persists
deployment. The wrapper's job is therefore not to *enable* the pattern
but to *automate* path computation, breadcrumb lifecycle, and
verification — operational ergonomics, not new capability." This
reframes the wrapper as a quality-of-life improvement rather than a
correctness fix, which is probably what it actually is, and makes it
much easier to ship a small v0 (CI-4).

### CI-4. There is no v0. The plan jumps from spec to a 4-track 20-task v1.

**Issue.** Tracks A through E have ~22 tasks. Estimated complexity
ranges from "small" to "medium" with no "trivial." There is no story
for shipping the smallest valuable thing first and iterating. The
Architect did not push back on this.

A v0 could be:
  - One file: `plugins/omh/omh_delegate.py`, ~80 lines.
  - One function: computes path, writes pre-dispatch breadcrumb, calls
    `delegate_task`, verifies file exists, returns `{ok, path,
    breadcrumb}`. **No fallback branch. No batch. No recovery CLI. No
    helper extraction.**
  - Three tests: happy path, contract violation (returns `ok=false`,
    raw preserved on breadcrumb), `delegate_task` raises (breadcrumb
    updated with error).
  - One skill migrated (omh-ralplan), one phase (e.g., planner only).

That ships in a day. It exercises the contract on real dispatches and
gives us the CI-2 measurement *for free*. If contract-obedience is
high, v1 = v0 + batch + skill rollout, total ~6 tasks, no fallback. If
contract-obedience is low, v1 = v0 + the Architect-approved hybrid.

**Impact.** The current plan commits to the maximalist design before
measuring. If CI-2's data says contract-obedience is 95%+, half of
Tracks A-E is wasted code that has to be maintained, tested, and
reasoned about forever.

**Suggested fix.** Replace §2's track structure with a **v0 / v1 / v2**
phasing:
  - v0: minimal wrapper, no fallback, one skill, three tests. (Days.)
  - v1: helpers extracted (A1/A2), batch (B6), tool registration (B7),
    remaining skills (D2-D4). Add fallback IFF v0 measurement requires
    it. (Week.)
  - v2: recovery CLI (C2), session_id capture (C1), GC, observability
    (M2). (Later.)

This is the same code, in the same modules, but ordered to maximize
learning per unit of risk. The Architect's C2 (OQ1 is a blocker for
B5) becomes moot because v0 doesn't try to parse `delegate_task`'s
return shape — it just checks whether the file exists.

### CI-5. The recovery branch's classifier (Architect C4) is unspecifiable in principle.

**Issue.** The Architect's proposed `classify(raw)` decision table
looks tidy:
```
PATH_MATCH, PATH_DRIFT, CONTENT, DICT, EMPTY
```
But `looks_like_path(s)` is undecidable on adversarial inputs. A
markdown artifact starting with `# /home/dt/...` matches a "looks like
path" regex on its first line. A path string longer than 32 chars
trips the CONTENT branch. A subagent that returns `"OK: wrote to
/abs/path/foo.md"` is neither path nor content nor empty — it's
*acknowledgment*. The classifier needs ~10 more cases and each one is
a heuristic.

This is the thing that scares me most about the hybrid. The fallback
branch's correctness depends on a classifier that is fundamentally
heuristic, used in exactly the cases where the subagent has already
demonstrated it doesn't follow instructions. That is the worst possible
combination for a heuristic.

**Impact.** Subtle data corruption in the rescue branch. The wrapper
will sometimes save the wrong thing as if it were the right thing.
This is *worse* than the FM1 it's replacing, because at least FM1's
loss was obvious (no file).

**Suggested fix.** Tied to CI-1: drop the rescue branch entirely (v0),
or if kept (v1+), require the subagent's return to include a sentinel
marker (`<<<RESULT>>>…<<<END>>>`) and only rescue if the marker is
present. No marker → `ok=false`, raw preserved on breadcrumb, no file
written. This makes the rescue path deterministic and removes the
classifier.

---

## 3. Warnings (should address)

### W1. Concurrency analysis stops too early.

The Architect's C1 covers RMW races on breadcrumbs. Good catch. But
the broader concurrency story is also under-examined:
  - Hermes runtime itself may do background work (autosave, indexing,
    log rotation) touching `.omh/state/`. The plan assumes Hermes is
    inert wrt the plugin's filesystem. Verify.
  - `omh_state` is touched by other tools (state_tool) potentially
    during a dispatch. If the state file and the dispatch breadcrumb
    interact (they shouldn't, but the plan doesn't say they don't),
    races exist.
  - Two `omh_delegate` invocations from the same orchestrator (e.g.,
    the orchestrator dispatches a sub-orchestrator that itself
    dispatches) are not addressed. Single-orchestrator is asserted but
    not enforced.

**Mitigation.** Architect's M1 ("state single-orchestrator as explicit
non-goal") is right but insufficient. Add a runtime assertion: the
breadcrumb directory contains a `.lock` sentinel naming the holder PID;
on collision, raise. Cheap, catches real bugs.

### W2. The 240-char goal preview is a privacy/secret leak vector.

OQ5 proposes a 240-char goal preview in breadcrumbs. Goals in OMH skills
sometimes include API keys, repo paths, or user PII bleed-through from
context. Breadcrumbs are written to disk that may be in a synced
directory, backed up, or rsynced. The Planner waves this off ("callers
must avoid putting secrets in goal") but skill prose is the caller and
skill prose is hand-written and humans are bad at this.

**Mitigation.** Either (a) drop goal preview entirely and store only a
hash for correlation, or (b) regex-scrub common secret patterns before
writing. Document explicitly that breadcrumbs are not secret-safe.

### W3. The "shim that falls back to delegate_task" is a third codepath nobody tested.

B8 specifies a degrade-to-passthrough behavior when the breadcrumb dir
is unwritable. This is a *third* codepath (alongside subagent-persists
and wrapper-persists). It is tested once (the unwritable-dir test) and
then forgotten. In production, on the day someone's `.omh/` is
read-only because of a Docker volume mount, the wrapper will silently
degrade and the operator will be confused why dispatches "work" but
nothing is on disk.

**Mitigation.** Make B8 raise loudly by default. Provide
`omh_delegate(..., allow_degrade=True)` for callers who explicitly opt
in. Skill prose should not opt in.

### W4. The OQ reductions the Architect made are mostly fine, but OQ3 deserves a real answer not a "boundary clarification."

OQ3 (project_root discovery without OMH config) is the kind of question
that becomes a P0 bug six months in when someone runs `omh_delegate`
from a non-OMH-aware tool. M7 says "state the boundary." That's the
minimum. Better: have `omh_delegate` walk up from cwd looking for a
`.omh/` marker, falling back to cwd, exactly mirroring how `git`
discovers `.git`. This is 5 lines and removes the entire boundary
question.

### W5. No story for skill-author error reporting when contract violation happens.

Today, when delegate_task drops output, the orchestrator notices in the
chat. With the wrapper (especially with the fallback), failures become
JSON fields nobody reads. Where does `recovered_by_wrapper=true` show
up to the human? In a log? In the orchestrator's next turn? The plan
is silent. This is the operability story and it is missing.

**Mitigation.** Wrapper SHOULD print a one-line warning to stderr on
any non-clean dispatch (recovery, drift, error). Cheap, catches
attention.

### W6. R7 (cross-fs replace) is named but not handled.

The Planner mentions cross-device `os.replace` failure as a risk and
proposes "raise a clear error." That punts to the operator. In practice,
if `.omh/` straddles a fuse mount (very common in dev containers), every
dispatch fails. Fix: detect at startup, log once, fall back to non-atomic
write with a warning. Or refuse to start. Either is better than
per-dispatch surprise.

---

## 4. Pushback on Architect's specific points

- **C1 (RMW concurrency) — agree, but I'd go further.** The Architect's
  "append-only events" suggestion (option 1) is the right fix and should
  be mandatory, not "I lean toward." It also obviates the need for
  the C2-suggested single-writer documentation and the C3 optimistic
  concurrency. Pick one; pick the simplest; mandate it.
- **C2 (OQ1 blocks B5) — agree but mooted by CI-4.** If v0 doesn't
  parse `delegate_task`'s return at all (just checks file existence),
  OQ1 stops being a blocker. Resolve via design simplification, not
  scheduling.
- **C3 (A3 over-coupled) — agree, minor.** The split is correct.
- **C4 (path-drift classifier) — see CI-5.** Architect's 5-class table
  is necessary but not sufficient; in adversarial cases it's
  fundamentally heuristic. My recommendation: don't write the
  classifier; require a sentinel marker.
- **C5 (verified semantics overloaded) — strongly agree.** Architect's
  three-boolean fix (`file_present`, `contract_satisfied`,
  `recovered_by_wrapper`) is essential, not optional. Without it the
  whole observability story is a lie.
- **M1-M7 — accept all.** Add: M8 (operability — see W5), M9
  (concurrency assertions — see W1), M10 (secrets-in-breadcrumb policy
  — see W2).

---

## 5. Smallest version that ships

For the parent's explicit "smallest version" question:

```
plugins/omh/omh_delegate.py   ~80 lines
plugins/omh/tests/test_omh_delegate.py   ~120 lines, 3-4 tests
```

Behavior:
  1. Compute `expected_output_path` from (mode, phase, ts).
  2. mkdir parents.
  3. Write breadcrumb at `.omh/state/dispatched/{id}.json`
     (single-write, append-only schema, no future RMW).
  4. Inject `<<<EXPECTED_OUTPUT_PATH>>>` block + brutal contract.
  5. Call `delegate_task(goal=augmented_goal, **passthrough)`.
  6. Verify file exists.
  7. Write completion breadcrumb `{id}.completed.json`
     (separate file, append-only).
  8. Return `{ok: file_present, path, breadcrumb_id}`. **No fallback.**
     **No content rescue.** **No batch.**

Tests:
  - Happy path (mock delegate_task; assert file present, breadcrumbs
    written, ok=True).
  - Subagent fails to write (assert ok=False, no rescue, raw return
    captured on completion breadcrumb).
  - delegate_task raises (assert breadcrumb has error, exception
    re-raised).

That's v0. It ships in one PR. Migrate one ralplan phase (planner) to
prove it. Measure contract-obedience over the next ~50 dispatches.
Then decide whether v1 needs the fallback at all.

This is roughly **15% of the code in the current plan**, exercises the
same risk surface, and answers CI-2 empirically before we commit to
the maximalist design.

---

## 6. Approval Conditions

If the plan is revised toward what I'd APPROVE:

  1. **Add task C0 (contract-obedience microbenchmark)** as a precondition
     to any decision about whether the wrapper-persists fallback ships.
  2. **Restructure §2 as v0 / v1 / v2 phasing** (CI-4). Land v0 before
     scoping v1.
  3. **Default to dropping the rescue branch in v0** (CI-1). If v1 adds
     it, the rescued artifact MUST carry an in-band sentinel header AND
     `ok` MUST surface as a non-true value (CI-1, CI-5).
  4. **Adopt append-only breadcrumb events** (Architect C1 option 1,
     mandated).
  5. **Adopt three-boolean status** (Architect C5, mandated).
  6. **Reframe §1 to acknowledge the bootstrap as evidence prose-only
     works** (CI-3).
  7. **Address W2 (secrets policy), W3 (no silent degrade), W5
     (operability)** explicitly.

With those changes, this becomes a small, tight, measurable v0 that
either validates the maximalist v1 or — more likely — reveals it was
never needed.

---

*End of Round 1 Critic review.*
