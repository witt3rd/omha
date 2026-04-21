# Round 1 — Architect Review: omh_delegate Plan

**Role:** Architect
**Reviewing:** round1-planner.md
**Date:** 2026-04-20

---

## 1. Verdict

**REQUEST_CHANGES** — small set, not structural.

The plan is fundamentally sound. Boundaries are clean, the hybrid is
defensible, the breadcrumb/schema decisions are coherent with existing
OMH conventions, and the track decomposition mostly respects real
dependencies. I am asking for changes (rather than approving) on
three concrete points: (a) the read-modify-write breadcrumb update path
needs a more explicit concurrency/ordering contract than "atomic write";
(b) at least two of the OQs are actually blockers for B5 detail, not
"during execution"; (c) Track A's ordering wires A3 too tightly into
B/C. None require redesign.

---

## 2. Strengths

- **Hybrid framing is honest.** §1 explicitly names the cost ("~5 lines
  on the fallback branch") and the benefit asymmetry (subagent-persists
  is the cheap common path; wrapper-persists is the cheap rescue). The
  hybrid does NOT muddy the contract because the contract toward the
  subagent is single-valued: "your last action is write_file at this
  exact path." The fallback is invisible to the subagent. The contract
  toward the *caller* is also single-valued: "the file at `result.path`
  exists." Two implementations behind one observable interface — that
  is a good abstraction, not a leak.

- **Module split (omh_io / omh_delegate / tools/delegate_tool) is right.**
  - `omh_io` as the home for `atomic_write_text` + `resolve_under_project`
    is the correct extraction; both are already duplicated implicitly
    across `omh_state.py` and `evidence_tool.py`. This pays down debt
    independent of the new feature.
  - `omh_delegate.py` as pure logic (no Hermes handler concerns) and
    `tools/delegate_tool.py` as the registration shim mirrors
    `state_tool.py` — consistent with the codebase.
  - The wrapper does not import from `tools/`; tools/ imports the
    wrapper. Dependency direction is correct.

- **Breadcrumb-per-dispatch (Q1) over rolling log.** Correct. Append-safe
  writes from multiple processes are a tarpit; per-file glob is fine for
  this volume. The decision composes with `omh_state`'s atomic pattern
  rather than introducing a second write discipline.

- **Path decision (Q2) — `.omh/research/{mode}/`.** Matches the
  just-landed convention and is the only choice that makes outputs
  reviewable in PRs. Co-locating with `state/` would have been wrong.

- **Strict mode/phase, loose passthrough (Q4).** mode+phase are the
  *primary key* for breadcrumb lookup and path computation; making them
  required is not gratuitous strictness, it is interface integrity.

- **Bootstrap story (Q11 close + R5).** Coherent. The current ralplan
  run uses prose-level subagent-persists (the orchestrator is manually
  writing this very file to `.omh/research/ralplan-omh-delegate/`),
  and post-D1 ralplan-on-self uses the tool. The recursion is real
  but bounded — the tool ships once, and from then on every dispatch
  is wrapper-mediated. No infinite regress.

- **Suffix-default collision (Q3).** Right default. The whole point of
  the wrapper is "don't lose evidence"; silent overwrite would defeat
  it. Exposing `overwrite="overwrite"|"refuse"` keeps power-users
  sovereign.

- **Fail-soft batch (Q8).** Correct for parallel debate roles.

- **R7 (cross-fs replace) is named.** Most plans miss this.

---

## 3. Concerns

### C1. Read-modify-write breadcrumb updates need an explicit ordering contract.

**What's wrong.** Q6 says "all writes use `omh_io.atomic_write_text`"
and B5 step 4 says "update breadcrumb." But a breadcrumb update is
*read JSON → mutate dict → write tmp → fsync → replace*. `atomic_write_text`
gives you crash-safety on the *write* half. It does NOT give you
last-writer-wins safety if two updaters race (e.g., a future
`omh_recover --reconcile` running while a dispatch is in flight; or a
batch where two task callbacks land near-simultaneously).

The single-process single-dispatch case is fine. But the design opens
two doors that make races plausible:
  - C2 recovery CLI explicitly mutates breadcrumbs (`recovered_by_cli=True`).
  - B6 batch could update sibling breadcrumbs in parallel if anything
    is hoisted out of per-task scope later.

**Why it matters.** A lost update on a breadcrumb means a recovered
artifact looks unverified, or a stale `verified=false` triggers a
spurious recovery. Not a correctness disaster, but the entire value
prop is "trustworthy trail." Trust degrades silently.

**Suggested fix.** Pick one and document it in B3:
  1. **Append-only events.** Don't mutate the breadcrumb file; write
     `{id}.json` at dispatch and `{id}.completed.json` (and
     `.recovered.json`) as separate files. Reader composes by glob.
     Eliminates the RMW entirely. Mild storage cost; trivial code.
  2. **Single-writer invariant.** Document "only the dispatching call
     mutates a breadcrumb until completion; recovery CLI only mutates
     breadcrumbs whose `completed_at IS NOT NULL OR dispatched_at <
     now-30m`." Add an assert.
  3. **Optimistic concurrency.** Add `_meta.revision` int; refuse
     replace if on-disk revision != expected. Heaviest, probably overkill
     here.

I lean toward **(1) append-only events** — it composes naturally with
`atomic_write_text`, eliminates a class of bugs, and the glob is cheap.

### C2. Two OQs are blockers, not "during execution."

**What's wrong.** OQ1 (`delegate_task` actual return shape) and OQ2
(pre-completion session_id availability) are listed under §5 as things
to resolve in C1. But B5's "parse pointer from raw return" and the
recovery branch's "if raw return contains substantive content" both
assume a return shape. If the return is `{result: str, session_id: str}`
vs `str` vs `{messages: [...]}`, the parsing code differs materially
and so does the test fixtures in E1.

**Why it matters.** B5 is on the critical path for everything in B6/B7/E1/D*.
Discovering OQ1's answer late means B5 gets rewritten and its tests get
rewritten.

**Suggested fix.** Promote OQ1 to a precondition for B5 — i.e., **C1
runs before B5, not in parallel with it.** OQ2 can stay as research; it
only affects whether session_id is in the dispatch breadcrumb or the
completion breadcrumb (and either is fine).

### C3. Track A ordering — A3 is over-coupled.

**What's wrong.** A3 ("seed `.omh/research/{mode}/` and
`.omh/state/dispatched/`") is listed as a Track A foundation, but its
acceptance criterion ("invoking `omh_delegate` once creates both dirs")
makes it depend on B5. It's really a *call-site responsibility* of the
wrapper (mkdir-on-write), not a foundation. As-listed it implies
modifying `omh_state`'s seeding logic to know about wrapper-specific
dirs — that leaks wrapper concerns back into the foundation.

**Why it matters.** Couples the foundation module to the consumer.
Adds a synchronization point ("don't start B until A3 is done") that
isn't necessary.

**Suggested fix.** Split A3 into:
  - A3a: extend `omh_state` auto-seeding to ensure `.omh/research/`
    exists and `.omh/.gitignore` covers `state/dispatched/` (this is
    pure layout policy, no wrapper coupling).
  - A3b → fold into B3 / B5: wrapper does
    `path.parent.mkdir(parents=True, exist_ok=True)` before
    `atomic_write_text`. That's one line per writer, no shared module.

### C4. Path-drift detection is described but not specified.

**What's wrong.** R1 mentions "we add a regex check that flags drift
in the breadcrumb" and E1 mentions "subagent returns *different* path".
But B5's flow doesn't define how the wrapper distinguishes
"subagent returned the expected path string" from "subagent returned
a different path" from "subagent returned content." Without a defined
extractor (returns `Either[Path, Content, Empty]`), the recovery branch
condition ("substantive content > 32 chars") is ambiguous — what if it
returns a path string that happens to be > 32 chars?

**Why it matters.** This is the verification logic. Vague rules → buggy
recovery → silent data loss in exactly the failure mode the wrapper
exists to prevent.

**Suggested fix.** Specify in B5:
  ```
  classify(raw) ->
    PATH_MATCH    if raw is str and Path(raw).resolve() == expected
    PATH_DRIFT    if raw is str and looks_like_path(raw) and != expected
    CONTENT       if raw is str and not looks_like_path(raw) and len > 32
    DICT          if raw is dict — extract per OQ1 contract
    EMPTY         otherwise
  ```
  And specify the action per class. This is a 10-line decision table;
  it should be in the plan.

### C5. `recovered_by_wrapper` writes a copy of the *raw return*, not a guaranteed-good artifact.

**What's wrong.** B5 step 3: "if missing AND raw return contains
substantive content, wrapper writes it." But the raw return from a
subagent that ignored the contract may be a chat-style preamble
("Here's the plan: …"), not the artifact in clean form. The wrapper
will dutifully save garbage to `expected_path` and mark `verified=true`.

**Why it matters.** `verified=true` becomes a lie. Downstream
consumers (Critic, next-round Planner) read garbage and propagate it.

**Suggested fix.** Either:
  - Mark recovered artifacts with a sentinel header
    (`<!-- recovered_by_wrapper: contract violated, raw subagent return below -->`)
    so downstream consumers and humans can tell, and keep
    `verified=true` semantically meaning "file exists" — rename to
    `file_present` if needed.
  - Or split: `file_present: bool`, `contract_satisfied: bool`,
    `recovered_by_wrapper: bool`. Three booleans; cheap; honest.

I prefer the second; the plan currently overloads `verified` with two
meanings.

---

## 4. Missing

- **M1. Concurrency model is unspecified.** The plan assumes a single
  orchestrator process. Realistic for v1, but should be stated as an
  explicit assumption in §1 (and a non-goal in §6) so future readers
  don't add multi-writer features atop a single-writer foundation.
  (Related to C1.)

- **M2. No interface for "list in-flight dispatches."** Q1 mentions
  `omh_recover --list` but it's not a task. The breadcrumb pattern is
  worthless without a reader. Add a small task (could live in C2 or as
  C2.5): `omh_io.list_dispatches(state_dir, *, only_unverified=False)
  -> list[Breadcrumb]`. Trivial code, but it's the API any recovery /
  steering / observability tool needs. Without it, every consumer
  re-implements glob+json.load.

- **M3. No story for stale breadcrumbs from prior runs at startup.**
  Fresh ralplan run starts in a repo with five days of orphan
  `verified=false` breadcrumbs. Are they ignored? Surfaced? GC'd?
  Answer can be "ignored, document GC command" but the plan should say
  so. (Touches R3 but doesn't close it.)

- **M4. The `<<<EXPECTED_OUTPUT_PATH>>>` injection has no specified
  position.** Prepend? Append? Wrap the whole goal? Subagents tend to
  weight final instructions heavily; appending is probably right but
  the plan should say so (B4) and the test should verify it.

- **M5. No mention of how the wrapper interacts with skill prose that
  *also* tries to specify an output path.** What if a skill author
  writes `omh_delegate(goal="...write to /tmp/foo.md...")`? Wrapper
  silently overrides. Probably fine, but worth documenting: the
  wrapper's path always wins; skill prose should not pre-bake paths.

- **M6. Test for the "subagent honored contract perfectly" path is
  implied but not the *first* test case.** E1 leads with crash/recovery
  cases. The happy path (subagent returned the expected path string,
  file is on disk, no recovery needed, breadcrumb updated cleanly)
  should be E1's first test — it's the case that runs 99% of the time
  and the one whose regression hurts most.

- **M7. OQ3 (project_root discovery without OMH config) is silently
  load-bearing for OQ-not-listed: "what happens if a non-OMH-aware
  caller invokes omh_delegate?" Probably "we require OMH config" — say
  so explicitly; it's a reasonable boundary, but it should be stated.

---

## 5. Verdict on the specific points the parent flagged

- **Hybrid (subagent-persists primary + wrapper-persists fallback):**
  Justified. The hybrid does not muddy the contract toward either
  endpoint; it is two implementations of one observable. Approve.

- **Module structure (omh_io / omh_delegate / tools/delegate_tool):**
  Boundaries clean. omh_io extraction pays down real existing duplication.
  Approve.

- **Track decomposition:** Mostly correct. Two adjustments: C1 must
  precede B5 (C2 above); A3 should be split (C3 above). Otherwise the
  parallelism in §2.7 is appropriate.

- **Breadcrumb schema and lifecycle / RMW pattern:** Schema is good.
  Lifecycle has the unaddressed RMW concurrency gap (C1 above).
  Recommend append-only event files instead of in-place mutation.

- **OQs as blockers:** OQ1 is a blocker (C2). OQ2 is a quality knob,
  not a blocker. OQ3 is a boundary clarification, should be stated not
  resolved (M7). OQ4 is post-launch tuning. OQ5 (240 chars) is fine
  as proposed. OQ6 (naming) is bikeshed — keep `omh_delegate`, the
  spec already commits to it.

- **Bootstrap recursion:** Coherent. The plan correctly identifies that
  *this* round runs on prose-level discipline and post-D1 rounds run
  on the tool. The artifacts of *this* run are exhibit A that prose
  works well enough to bootstrap. No regress.

---

*End of Round 1 Architect review.*
