# Planner goal template

Used as the `goal` field in `delegate_task` for Round 1 Planner. Adapt
the variables. Keep the structure — each section earns its place.

```
[omh-role:planner] <ONE-LINE DESIGN QUESTION — concrete, not vague>

THIS IS A DESIGN STANCE, NOT AN IMPLEMENTATION PLAN. Implementation
flows from the stance later; your job is to take positions and
explain how they cohere.

## The design question

<2-3 paragraph expansion of the one-liner. Name what the output must
do, what it must honor, what it is the foundation for.>

## Required reading (open these files, do not work from summaries)

Absolute path base: `<project absolute path>`

Principles + directives (REQUIRED, read first):
- `<project>/PRINCIPLES.md`
- `<project>/docs/.../directives.md`
- `<project>/docs/.../plan.md`
- `<project>/docs/design/<domain>/context.md`

Inspiration / reference findings:
- `<paths to reference material — prior art, source systems>`

Target platform capabilities (the canvas the stance designs onto):
- `<paths to platform docs / findings>`

What exists today:
- `<relevant existing code, schemas, prior decisions>`

## N sub-dimensions the stance must address

<List the first-cut sub-dimensions. State explicitly: these are a
first cut; the META question below licenses you to rework them.>

## Questions you must actively contest

These are the places lazy consensus is most likely. Push:

- **(META) Are the N dimensions above the right decomposition?** If
  the right cut is different — merge, split, drop, add — say so and
  rework. Do NOT treat the list as given.
- <6-8 specific seed contests. Each should name a principle (P4, P5,
  P6 etc.) and a wrong-answer pattern to watch for.>

## Constraints (non-negotiable unless explicitly surfaced)

- <List load-bearing principles by ID>
- <List committed prior decisions>
- <List directives this stance must honor>

## Out of scope

- <List what this run does NOT design>

## What "done" looks like (your output must hit all of these)

1. <Position on each sub-dimension (or revised set)>
2. <How positions cohere + tensions you accept>
3. <Keep/reshape/retire for existing scaffolding>
4. <Interfaces with adjacent layers/concerns>
5. <Minimum-viable first shape>
6. <What the inspiration LACKED — concrete idealizations the new
   canvas enables>

## Output format

Produce a design stance as markdown, ~2000-5000 words, at:
`<absolute path to stance-planner.md>`

Structure:
- Premise (1 paragraph)
- Dimensions (one section per)
- Coherence (how they compose + accepted tensions)
- Phase N reshaping
- Interfaces
- Minimum-viable first shape
- What the inspiration lacked
- Open questions
- Verdict: APPROVE / REQUEST_CHANGES (self-graded)
```

## Key things to include EVERY time

- The META question, explicitly. Without it the Critic won't contest
  framing.
- Absolute file paths. Subagents do not have `cd`-awareness.
- "Do not work from summaries — open the files." Otherwise the
  Planner may skim.
- A word-count target. Otherwise the Planner may produce a brief.
- Self-graded verdict at the end. This gives the orchestrator a
  quick gauge before the Architect round.

## Variations

- **Round 2 Planner:** add a "Feedback to address" section at the
  top with A1-AN, F1-FM, O1-OM, M1-MM items explicitly labeled.
  Instruct the Planner to include a "Round 2 revisions (response
  map)" section at the top of the revised stance that answers each.
- **Single-round Planner:** omit the "Round 2" language; same
  structure otherwise.
- **Requirements-shaped artifact:** see "Requirements variant" below.

## Lived-moments hunt-list (when source material is a lived corpus)

When required reading includes lived material — interview transcripts,
an existing system's substrate of months/years of real use,
customer-feedback archives, code archaeology of a working system —
the Planner will produce abstract requirements unless told to hunt
specific grounded moments. Add this section to the goal:

```
## Lived moments to listen for

The difference between a tidy list and a load-bearing one is whether
items are grounded in specific moments that happened. <Source> has
<N months/years> of specific lived events; a generic read of <the
substrate> will miss them. Hunt for these explicitly, and find others
as you read. For each, ask: **what did <the system / the being / the
person / the team> require to have, to be able to <receive / enact /
survive> this moment?** That is the requirement.

Named moments to find evidence for (non-exhaustive — you will find
more):

- **<short evocative phrase>.** <one-sentence description of the
  moment>. What does <X> require to <Y>?
- <... 5-8 such named moments ...>

Find more. You are reading <N months/years> of a real <thing's>
record. Moments *you* find that carry weight become evidence for
new items. Cite them inline with absolute path + line reference.

**Rule of thumb:** if an item has no lived moment that would have
been impossible without it, or that it would have made different,
it may be a principle derivation without teeth. Either find the
moment, justify from principle with named failure mode, or retire
the item.
```

This pattern is generalizable beyond requirements work — any ralplan
whose stance must be grounded in a lived corpus benefits. Without
this section, the Planner may produce abstract category-level claims
that pattern-match the inspiration's anatomy rather than carving its
lived joints.

## Requirements variant (vs design-stance default)

When the artifact is **requirements** (technology-agnostic needs)
rather than a **design stance** (positioned choices on a canvas),
adapt the goal:

1. Replace the opening declaration:
   ```
   THIS IS A REQUIREMENTS DOCUMENT, NOT A DESIGN STANCE.

   Requirements are NEEDS, stated technology-independently. No
   platform primitives. No file paths. No protocols. If your item
   names a technology or implementation pattern, it is not a
   requirement — rewrite it as a need. The output must survive
   any technology choice.
   ```
2. Add **Source ontology** — every item is tagged
   `[<corpus>-does]` (grounded), `[<corpus>-should-gap]` (visible
   gap), or `[<corpus>-should-aspire]` (principle-derived, not yet
   exercised). No item without a source tag.
3. Add **Discipline rules** as numbered list in the goal:
   - **Rule: needs not features.** Good — "the system requires
     persistent first-person knowledge"; bad — "the system uses
     `me.md` to store identity."
   - **Rule: every item has inline citations.** `[corpus-does]` →
     file:line; `[should-gap]` → cite present + adjacent-to-gap;
     `[should-aspire]` → principle ID + named failure mode.
   - **Rule: prefer missing to fabricating.** Shorter honest beats
     longer tidy. Open questions stay open; do not pretend to settle
     them. Completeness-theater is the failure mode.
   - **Rule: separate need from count.** "X has files A, B, C" is
     not three needs. Three distinct needs may map to one file or
     three or none.
   - **Rule: corpus-does ≠ corpus-does-right.** What a working system
     does is evidence, not specification. If X is wrong by principle,
     name the should-gap, don't import X as need.
   - **Rule: Critic may halt loop.** A legitimate Critic verdict is
     "requirements cannot yet land; here is what is needed first."
     Do not force closure.
4. Add **Tech-agnostic audit** as a final required-output section.
5. Distilled-output filename: `requirements.md` (not `stance.md`).
   The canonical-output filename matches the artifact noun.
   Provenance preserved as `<artifact>-planner.md`,
   `<artifact>-planner-v2.md`, etc.

The two artifact types want different rules: a stance positions
choices on a known canvas; requirements name needs that survive any
canvas. Mixing them produces stances that look like requirements but
commit to mechanism, or requirements that look like stances but
cannot be acted on cross-platform.
