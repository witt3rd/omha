---
name: omh-deep-research
description: >
  Multi-phase web research that decomposes a topic into subtopics, dispatches
  parallel researcher subagents, synthesizes a report, and verifies citations
  before marking it confirmed. State is durable: kill at any phase boundary
  and re-invoke to resume. Sentinel: `.omh/research/{slug}-report.md` with
  frontmatter `status: confirmed`.
version: 1.0.0
tags: [research, web, synthesis, parallel, omh]
category: omh
metadata:
  hermes:
    requires_toolsets: [terminal, omh, web]
---

# OMH Deep Research — Multi-Phase Web Research with Citation Verification

## When to Use

- The user asks for "deep research on", "a research report about",
  "comprehensive research", "investigate X", "what's known about Y"
- omh-deep-interview encounters an unfamiliar domain and needs background
- omh-ralplan needs external context before it can plan responsibly
- The user's question requires synthesizing 3+ web sources into one
  coherent answer, not a single search

## When NOT to Use

- A confirmed report already exists at `.omh/research/{slug}-report.md`
  with `status: confirmed` for this topic — view it instead
- The question is answerable by a single web_search call
- The user wants real-time / current-events data only (this skill
  emphasizes durable synthesis, not freshness)
- No `web` toolset is available in this Hermes install (see Prerequisites)

## Prerequisites

This skill fail-fasts if any of the following are missing:

- **`web` toolset** — provides `web_search` AND `web_extract`. If either
  is unavailable, print:
  ```
  omh-deep-research requires the `web` toolset (web_search + web_extract); aborting.
  ```
  and exit before doing any work.
- **`omh_state` tool** — preferred path. If absent, fall back to manual
  JSON read/write at `.omh/state/research--{slug}.json` (per-instance —
  `{slug}` is the kebab+date+random4 minted in Phase 1; multiple research
  topics can run concurrently). If neither is writable, fail-fast with a
  clear error.
- **Write access** to `.omh/` for state, plan, findings, report, log.

Hermes discovery: `hermes skills list | grep omh-deep-research` should
return this skill once installed.

### Installation (symlink for Hermes discovery)

```
mkdir -p ~/.hermes/skills/omh && ln -snf <repo>/plugins/omh/skills/omh-deep-research ~/.hermes/skills/omh/omh-deep-research
```

Parent dir creation MUST precede the symlink.

## Architecture

Five invocation phases, exit-safe between any two:

| # | Phase     | Reads                                  | Writes                                                       | Subagents |
|---|-----------|----------------------------------------|--------------------------------------------------------------|-----------|
| 1 | decompose | user query                             | `{slug}-plan.md`, state.phase=search                         | none      |
| 2 | search    | plan, state, findings/                 | new findings file(s), state.completed_subtopics, phase       | 1-3 `[omh-role:researcher]` parallel |
| 3 | gap_check | all findings                           | optional `_followup.md` OR direct phase flip                 | 0 or 1 `[omh-role:researcher]` |
| 4 | synthesize| all findings (parent inlines)          | `{slug}-report.md` `status: draft`, phase=verify             | 1 `[omh-role:research-synthesist]` |
| 5 | verify    | report + findings (parent inlines)     | confirmed frontmatter / state mutate / blocked               | 1 `[omh-role:research-verifier]` |

**Per-instance state.** Each research session lives at
`.omh/state/research--{slug}.json` (the engine slugifies `instance_id`
into the filename). Multiple topics can be in flight concurrently — the
slug minted in Phase 1 IS the instance_id, and every subsequent
`omh_state(...)` call passes `instance_id="{slug}"`. Per-session
artifacts (plan, findings, report) are slug-keyed under
`.omh/research/`. The earlier `research-{id}.json` and
`research-state.json` (singleton) wordings from older specs are
superseded.

**Parent owns the filesystem.** All web tool use happens inside delegated
subagents. The parent reads findings files and inlines their contents
into synthesist's and verifier's `context` field. Subagents return
text only.

**Roles are referenced, never inlined.** Use `[omh-role:NAME]` markers.
The full role bodies live in `plugins/omh/references/role-*.md`.

## Procedure

### Phase 0: Check for Existing State and Sentinel

Before starting any new research session:

1. **Mint a candidate slug** for the new request (see Phase 1 rule).
   Call this `new_slug`. We need it to disambiguate enumeration below.
2. **List existing research instances** —
   `omh_state(action="list_instances", mode="research")`. If the tool is
   unavailable, glob `.omh/state/research--*.json` manually. Each entry
   carries an `instance_id` (== slug) and `active` flag.
3. **For each active entry**, run a cancel check first:
   `omh_state(action="cancel_check", mode="research", instance_id="{slug}")`.
   If cancelled, log `CANCELLED slug={slug}` and clear that instance via
   `omh_state(action="clear", mode="research", instance_id="{slug}")`.
4. **Sentinel self-heal (recovery from crash between confirm and
   clear).** For each remaining active entry whose
   `.omh/research/{slug}-report.md` has frontmatter `status: confirmed`,
   the previous run crashed after writing the sentinel but before
   clearing state. Treat as completed: log
   `REPORT_CONFIRMED_RECOVERED slug={slug}`, clear via
   `omh_state(action="clear", mode="research", instance_id="{slug}")`.
5. **Topic-match resume** — if any remaining active entry's `topic`
   matches the new request, jump directly to Phase 2/3/4/5 for THAT
   slug (use its existing `instance_id`); do not mint `new_slug`.
6. **Already-confirmed for this topic** — if a `{slug}-report.md`
   exists with `status: confirmed` matching the new topic, prompt:
   refresh (mint a new slug and re-run) / view existing report / cancel.
7. **No conflict** — proceed to Phase 1 with `new_slug`. Concurrent
   active research on different topics is permitted; do not block.

### Phase 1: Decompose

1. Cancel check: `omh_state(action="cancel_check", mode="research", instance_id="{slug}")`.
2. **Mint a slug** — concrete rule:
   `slug = kebab(topic)[:40] + '-' + YYYYMMDD + '-' + random4`
   where `random4` is 4 lowercase-hex chars.
   `kebab()` = lowercase, replace runs of non-alphanumeric with `-`,
   strip leading/trailing `-`, truncate to 40 chars.
3. Decompose the user's topic into 3-5 subtopics. For each subtopic,
   draft 2-3 candidate search queries.
4. **Write the plan** atomically (tmp → fsync → rename) to
   `.omh/research/{slug}-plan.md` with frontmatter:
   ```
   ---
   status: planning
   topic: {original user topic}
   slug: {slug}
   subtopics:
     - name: {subtopic 1 name}
       queries: [{q1}, {q2}, {q3}]
     - ...
   ---
   ```
5. **Initialize state** via `omh_state(action="write", mode="research", instance_id="{slug}", data={...})`:
   ```
   {
     "phase": "search",
     "slug": "{slug}",
     "topic": "{topic}",
     "subtopic_count": N,
     "completed_subtopics": [],
     "started_at": "{ISO-8601}",
     "session_id": "{uuid4}",
     "synthesis_attempts": 0
   }
   ```
6. Log `STARTED slug={slug}` and `PLAN_WRITTEN slug={slug} subtopics=N`.
7. Exit. Re-invocation will pick up at Phase 2 via the Phase 0 resume path.

### Phase 2: Search (parallel batched, re-entrant)

This phase is **re-entrant**: it dispatches one batch of up to 3
researcher subagents per invocation, then exits. Re-invoke to dispatch
the next batch. Re-entry is driven by `state.completed_subtopics`.

1. Cancel check: `omh_state(action="cancel_check", mode="research", instance_id="{slug}")`.
2. Read state and the `{slug}-plan.md` frontmatter.
3. Compute `pending = [s for s in plan.subtopics if s.name not in state.completed_subtopics]`.
4. Take the next `batch = pending[:3]` (up to 3 in parallel).
5. **Dispatch ONE batch call** with the `[omh-role:researcher]` marker:
   ```
   delegate_task(tasks=[
     {
       "goal": "<self-contained: topic, subtopic name, exact queries to run, output template per [omh-role:researcher]>",
       "context": "<plan excerpt for this subtopic; no other subagent's findings>",
     },
     ...up to 3...
   ])
   ```
   Each task's `goal` is fully self-contained — no inter-subagent
   dependencies. The role marker `[omh-role:researcher]` MUST appear in
   each goal so the subagent loads the role.
6. **(Strict write-order — NEVER reverse this order):**
   1. Write all findings file(s) for this batch atomically
      (tmp → fsync → rename). Each file lands at
      `.omh/research/{slug}-findings/{subtopic-slug}.md` with
      frontmatter capturing `subtopic`, `source_urls`, and credibility
      tags pulled from the subagent's returned SOURCES block.
   2. Update `state.completed_subtopics` (extend the list, persist via
      `omh_state(action="write", mode="research", instance_id="{slug}", data=...)`).
   3. Exit.
7. **Phase transition.** On the next invocation, Phase 0 routes back
   here. If `pending` becomes empty after the write, set
   `state.phase = "gap_check"` BEFORE exiting (still after the
   findings write — order: findings → completed_subtopics → phase flip).
8. Log `BATCH_COMPLETE batch=N subtopics=[name1,name2,...]` per batch.

**Pitfalls specific to Phase 2:**

- **Dedup across subtopics.** Two researchers may surface the same URL.
  The synthesist (Phase 4) handles cross-subtopic dedup via global
  Sources renumbering; Phase 2 does NOT need to dedup across files.
- **Slug for findings filename.** Use `kebab(subtopic.name)[:60]`. If
  two subtopics kebab to the same slug, append `-2`, `-3`, etc.
- **Parent never calls `web_search` or `web_extract` directly.** All
  web tool use is inside the delegated `[omh-role:researcher]`
  subagents. The parent's job is dispatch and disk.

### Phase 3: Gap Check (TWO branches only)

The parent skill never calls `web_search` or `web_extract` directly;
all web tool use happens inside delegated subagents.

1. Cancel check: `omh_state(action="cancel_check", mode="research", instance_id="{slug}")`.
2. Read all `.omh/research/{slug}-findings/*.md` files. From each, extract
   the `GAPS:` bullet list. Concatenate, then **dedup lexically**
   (case-insensitive trim-compare; preserve first occurrence).
3. **TWO branches only:**

   - **(a) 0 gaps** — Set `state.phase = "synthesize"`, log
     `GAP_CHECK_COMPLETE gaps=0`, exit.

   - **(b) ≥1 gap** — Delegate ONE `[omh-role:researcher]` subagent.
     Goal: synthetic "subtopic" named `_followup`, with the deduped gap
     list as the queries. Parent writes the returned text to
     `.omh/research/{slug}-findings/_followup.md` (atomic). Set
     `state.phase = "synthesize"`, log `GAP_CHECK_COMPLETE gaps=N`, exit.

   No threshold tiers. No N-versus-M gap branching. No inline
   web_search branch. Two branches only — that is the contract.

### Phase 4: Synthesize (parent inlines findings; parent writes report)

1. Cancel check: `omh_state(action="cancel_check", mode="research", instance_id="{slug}")`.
2. **Parent INLINES findings.** Read ALL files under
   `.omh/research/{slug}-findings/` (including `_followup.md` if
   present). Concatenate their full contents into the delegation's
   `context` field. The synthesist subagent has no filesystem access.

   **Budget escape (verified safe).** If the concatenated payload
   exceeds the orchestrator's tool-arg budget (≈40KB+ across 5+
   findings files is a soft threshold), the parent MAY summarize
   each findings file's SYNTHESIS section while preserving:
     - The full SOURCES `[N]` block verbatim (titles + URLs + tags + dates)
     - All GAPS sections verbatim
     - The `_followup` block verbatim (it is usually the smallest and
       most claim-dense)
   Do NOT drop or paraphrase any URL, citation tag, or numeric claim.
   Dogfooded 2026-04: a 5-subtopic + 1-followup run with summarized
   SYNTHESIS bodies + verbatim source lists passed verification at
   high confidence with all 28 globally-renumbered citations intact.
   When in doubt, prefer full inline; summarize only when forced.
3. Dispatch ONE `[omh-role:research-synthesist]` task:
   ```
   delegate_task(
     goal="<self-contained: produce report per [omh-role:research-synthesist] template; topic={topic}; reference inlined plan + findings>",
     context="<plan frontmatter + every findings file content, fully inlined>",
   )
   ```
4. **Retry context.** If `state.synthesis_attempts > 0`, append the
   prior verifier's REQUEST_CHANGES feedback (stored in
   `state.last_verifier_feedback`) to the goal as:
   ```
   Address these prior verifier findings:
   {feedback}
   ```
5. **Parent always overwrites** `.omh/research/{slug}-report.md` with
   the returned text. Frontmatter starts at `status: draft`. NO `-v2`
   suffixing. Prior verdicts live only in state, not on disk.
6. **C3 propagation.** Parent does NOT edit the returned report. Any
   `(insufficient sources for this subtopic)` strings remain verbatim.
7. Set `state.phase = "verify"`, log `REPORT_DRAFT`, exit.

### Phase 5: Verify (parent inlines; 3-strike gate; ordered confirm)

1. Cancel check: `omh_state(action="cancel_check", mode="research", instance_id="{slug}")`.
2. **Parent INLINES report + findings.** Read `{slug}-report.md` AND
   all `{slug}-findings/*.md` files. Concatenate BOTH into the
   verifier delegation's `context` field. Verifier subagent has no
   filesystem access.
3. **Tools allowlist (A5).** When dispatching, pass a tools allowlist
   EXCLUDING write/edit/filesystem tools where Hermes supports
   per-call tool scoping. If Hermes lacks per-call scoping, document
   in Known Gaps and rely on the prose READ-ONLY contract in
   `role-research-verifier.md`.
4. Dispatch ONE `[omh-role:research-verifier]` task. Parse the
   returned VERDICT.

5. **On VERDICT: PASS — STRICT ORDER (NEVER reverse):**
   1. Write `{slug}-report.md` with frontmatter `status: confirmed` (atomic; idempotent sentinel; THIS is the source-of-truth and must land FIRST).
   2. Append `REPORT_CONFIRMED slug={slug}` to the event log.
   3. Clear state via `omh_state(action="clear", mode="research", instance_id="{slug}")`.
   4. Print summary to user; exit.

   Phase 0 self-heals if a crash occurs between step 1 and step 3 (it
   detects the confirmed sentinel and clears the orphan state).

6. **On VERDICT: FAIL with `state.synthesis_attempts < 3`:**
   - Increment `state.synthesis_attempts`.
   - Store the verifier's REQUEST_CHANGES verdict (full body) in
     `state.last_verifier_feedback`.
   - Set `state.phase = "synthesize"`.
   - Log `VERIFY_FAIL slug={slug}` and `SYNTHESIS_RETRY attempt={N}`.
   - Exit. Re-invocation re-runs Phase 4 with feedback context.

7. **On VERDICT: FAIL with `state.synthesis_attempts == 3`:**
   - Set `state.phase = "blocked"`.
   - Surface the verifier's gap list to the user.
   - Log `VERIFY_FAIL slug={slug}` and `BLOCKED_RETRIES_EXHAUSTED slug={slug}`.
   - Exit. State is RETAINED so the user can inspect or escalate
     (Phase 0 will not auto-restart a blocked session).

## Logging

Append-only events to `.omh/logs/research-{session_id}.log`. Events are
decisions and phase transitions only — never findings content (matches
the omh-deep-interview convention).

Documented event vocabulary:

- `STARTED slug={slug}`
- `PLAN_WRITTEN slug={slug} subtopics=N`
- `BATCH_COMPLETE batch=N subtopics=[...]`
- `GAP_CHECK_COMPLETE gaps=N`
- `REPORT_DRAFT`
- `VERIFY_PASS`
- `VERIFY_FAIL`
- `SYNTHESIS_RETRY attempt=N`
- `BLOCKED_RETRIES_EXHAUSTED slug={slug}`
- `REPORT_CONFIRMED slug={slug}`
- `REPORT_CONFIRMED_RECOVERED slug={slug}`
- `BLOCKED slug={slug}`
- `CANCELLED`

## Sentinel

Downstream skills (omh-deep-interview, omh-ralplan, omh-autopilot) detect
a completed research session by:

```
.omh/research/{slug}-report.md  with frontmatter `status: confirmed`
```

This file is the durable contract. State is ephemeral; the sentinel is
the source of truth.

## Pitfalls

- **Never call `web_search` or `web_extract` from the parent.** All web
  tool use happens inside delegated `[omh-role:researcher]` subagents.
- **Never inline role text.** Use `[omh-role:NAME]` markers; bodies live
  in `plugins/omh/references/role-*.md`.
- **Phase boundaries are commit points.** Each phase MUST exit cleanly
  after writing its outputs and updating state. Long-running phases
  that span multiple delegations are not exit-safe.
- **One active research session per project.** Phase 0 enforces this.
  Don't create parallel research states.
- **Slug collisions are user-visible.** The `random4` suffix keeps
  same-topic same-day re-runs from clobbering each other.

## Known Gaps

- **Persistence to wiki / fact_store / memory** is not yet integrated.
  The sentinel report is the only durable interface in v1. (Q2)
- **Per-call subagent tool scoping for `[omh-role:research-verifier]`**
  may be unavailable depending on Hermes install; READ-ONLY contract is
  enforced by prose in `role-research-verifier.md` in that case. (A5)
