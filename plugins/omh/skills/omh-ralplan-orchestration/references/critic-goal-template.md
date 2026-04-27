# Critic goal template

Used as the `goal` field in `delegate_task` for Round 1 Critic.

**This is the most important template.** The Critic is the role that
produces the quality — without a well-prompted Critic, the ralplan
loop converges on internal consistency rather than truth. Get this
right.

```
[omh-role:critic] Critically challenge the <domain> stance AND the
Architect review. Do not just compliance-check. Contest the framing.

## Required reading

<same list as Architect, plus:>
- Architect review: <absolute path>

## Your job — contest, don't just verify

The context package licenses you to contest the framing itself. Use
that license.

### Contest levels

**Level 1 — The meta-framing.**
- Are <N> dimensions the right decomposition? Or is there a different
  cut entirely that the Planner missed because it stayed too close
  to <inspiration>'s own anatomy?
- <Specific meta-framing questions for this domain.>

**Level 2 — The ontology.**
- Where does the stance smuggle in shape that doesn't belong? <Name
  the specific trap the project already caught once and is watching
  for recurrences of.>
- <Specific ontology questions tied to principles P4, P5, P6.>

**Level 3 — The missing dimensions.**
- What is the stance NOT covering that the thing-being-designed
  actually lives? Some candidates for this domain:
  - <List 5-8 specific lived dimensions that might be missing>

**Level 4 — The simplicity test.**
- Is there a radically simpler shape that would work? (e.g., "just
  ship the substrate + manual trigger; everything else defers to
  lived use.")
- Is there something the stance proposes that is actually unnecessary
  and should be cut?

**Level 5 — The principle test.**
- Walk each of the <N> principles. For each: does the stance protect
  it, or does it sneak across?
- Particularly: any principle not mentioned at all in the stance.

## Output

Produce a ~1500-2500 word Critic response at:
<absolute path to review-critic.md>

Structure:
- Verdict: APPROVE / APPROVE_WITH_RESERVATIONS / REQUEST_CHANGES /
  REJECT (or one of the legitimate alternative verdicts below)
- Framing contests: F1, F2, F3... places where you challenge the
  meta-framing itself
- Ontology contests: O1, O2... where wrong-ontology has crept in
- Missing dimensions: M1, M2... things the being actually lives that
  the stance doesn't address
- Simplicity challenges: S1, S2... things that could be radically
  simpler
- Principle violations or near-misses
- Agreements with the Architect: where A1-AN are right
- Disagreements with the Architect: where A1-AN are wrong or
  insufficient
- Must-fix before consensus: prioritized list
- Things you'd let slide: explicit, so the orchestrator knows what's
  not load-bearing

Critic should CHALLENGE, not block, unless something is truly broken.
If the stance is basically right but the framing is wrong, say
REQUEST_CHANGES and explain. If it's basically right and the framing
is right, say APPROVE_WITH_RESERVATIONS and name them cleanly.

### Legitimate verdicts

In addition to APPROVE / APPROVE_WITH_RESERVATIONS / REQUEST_CHANGES
/ REJECT, you may return:

- **REQUEST_CHANGES-not-closable** — "this run cannot land because
  evidence is insufficient OR a principle is undecided. Here is what
  is needed first." Stronger than forcing APPROVE on a flawed
  artifact.

- **user-conversation-required: <crisp question>** — "this question
  requires the user's principled commitment, not more subagent work.
  Here is the question crisply." The orchestrator will escalate, get
  the answer, and encode it as Round 2 direction.

These are not failure modes. They are honest outcomes the loop exists
to produce.
```

## Key things to include EVERY time

- **Level 1 meta-framing contest explicitly licensed.** Without this,
  the Critic stays inside the frame.
- **Level 5 principle audit explicitly requested.** Walk each
  principle. Say "particularly: any principle not mentioned at all
  in the stance." This is what catches the silently-absent principle.
- **Concrete counter-proposals invited**, not just flagged concerns.
  "Propose a specific alternative if you have one" beats "flag
  concerns."
- **"Let slide" section required.** Critics can spiral into finding
  everything wrong. Forcing a "not load-bearing" list focuses them.

## The two biggest moves a good Critic makes (preserve the pattern)

1. **Propose a specific alternative.** Not "consider a different
   decomposition" — a concrete counter, named with its dimensions.
   The Round 2 Planner can then adopt it (or reject it) on principled
   grounds.

2. **Walk every principle and name absences.** Frequently the
   silently-absent principle — the one nobody mentioned because
   everyone was inside the frame that hid it — is the load-bearing
   catch. The Critic is the only role positioned to find this; the
   META question + principle audit licenses it.

## Round 2 variant: the counterfactual deference test

For Round 2 Critic invocations, the contest-levels block above is
secondary. The primary job is the deference test — sharpened to
counterfactual form. Add this block:

```
## Your specific Round 2 tests

### Test 1 — The counterfactual deference test (LOAD-BEARING)

The Planner adopted your Round 1 counter-proposal (a different
decomposition, a collapse, a reframe). Test whether the adoption was
*principled* (the alternative holds for its own reasons) or
*deferential* (the Planner adopted because you said so, and would
have adopted any plausible alternative similarly).

Sharpened test: **"Would this defense have been written if a
COUNTERFACTUAL Critic had proposed a DIFFERENT alternative?"**

Concrete pattern: if the Planner adopted decomposition B with three
principled grounds (e.g., P6, P1, P12) — imagine a counterfactual
Critic had proposed decomposition C. Would those same three grounds
also justify adopting C?

- **If yes, all three transfer:** generic principle-citation,
  deferential pattern-match. Verdict implications: REQUEST_CHANGES
  on shaky ground; demand the Planner specifically defend why THIS
  cut.
- **If some transfer, some don't:** defense is specific to chosen
  alternative. Principled adoption confirmed. Note which grounds
  transferred (generic) and which didn't (specific).
- **If none transfer:** unusually strong principled defense.

### Test 2 — Did any Round 1 suggestion get adopted that should have
been resisted?

Critics are sometimes wrong. Read your own Round 1 suggestions and
ask: was any not good advice? Did the Planner adopt something they
should have pushed back on?

### Test 3 — What did Round 2 make worse?

Round 2 revisions sometimes damage what was good in Round 1. Check
if the rework lost or diluted anything load-bearing from Round 1.

### Test 4 — New silently-absent principle

Round 1's biggest move catches the principle nowhere mentioned. Now
that those Round 1 catches landed in Round 2, is there a NEW
silently-absent principle? Walk all principles again. The new stance
has a new frame; new things may be silently absent inside it.

### Test 5 — Round 2 verdicts include APPROVE_WITH_PROVISO

If the Round 2 stance is basically right but needs two-to-four small
named additions (a missing principle statement, a contract
clarification, a failure-handling note), use:

**APPROVE_WITH_PROVISO: <crisp condition>** — "this approves IF the
planner adds X / cuts Y / clarifies Z. Surface-level additions,
foldable during distillation, no Round 3 needed."

Don't use PROVISO to avoid Round 3 ceremony for changes that actually
need it. If the proviso would touch multiple sections, change a
load-bearing decision, or require its own coherence check — that's
REQUEST_CHANGES, not PROVISO.
```

## When to use which variant

- **Round 1 Critic:** the contest-levels block above. Full license
  to contest framing. Include the legitimate-verdict classes
  (REQUEST_CHANGES-not-closable + user-conversation-required).
- **Round 2 Critic:** the counterfactual deference test block above.
  Specifically grade whether Round 1 catches were adopted principally,
  including APPROVE_WITH_PROVISO.

Both retain the principle-audit instruction and the let-slide section.

These are the moves good Critics make. Good Critic prompts invite
both shapes.
