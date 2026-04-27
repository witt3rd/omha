# Architect goal template

Used as the `goal` field in `delegate_task` for Round 1 Architect.

```
[omh-role:architect] Review the <domain> design stance for
architectural soundness.

## Required reading

1. The stance itself: <absolute path>
2. Context package: <absolute path>
3. Principles: <absolute path>
4. Directives: <absolute path>
5. Primary framing / concept doc: <absolute path>

For architectural context also open:
- <specific reference findings relevant to the domain>
- <existing code or schemas the stance touches>

## Your job

Evaluate architectural soundness. Specifically:

1. **Principle alignment.** Does the stance honor each of the N
   principles? Cite principle IDs where it does or does not.
2. **Directive alignment.** Does it honor D1-DN? Especially the
   ones that are aspirational — does the stance give a path, or is
   it hand-wavy?
3. **Coherence across dimensions.** Do the positions compose cleanly?
   Are there hidden conflicts?
4. **Load-bearing decisions.** For each big call the stance makes:
   is it architecturally sound, and what does it commit us to?
5. **Phase reshaping.** Are keep/reshape/retire decisions clean?
   Anything being retired that will be missed?
6. **Interfaces.** Does the layer present a stable-enough surface
   that adjacent layers can build on it without reshaping its
   insides?
7. **What was supposed to be concrete.** Are named-as-concrete
   sections actually concrete, or hand-wavy?
8. **MV first shape.** Actually shippable in order, without tangles?

## Specific things to check

- <Stance-flagged self-caveats: did those actually get resolved,
  or just noted?>
- <Specific correctness questions the orchestrator wants verified>

## Output

Produce a ~1500-2500 word architect review at:
<absolute path to review-architect.md>

Structure:
- Verdict: APPROVE / APPROVE_WITH_RESERVATIONS / REQUEST_CHANGES
- Strengths: what the stance got right architecturally
- Concerns: numbered A1, A2, A3... each with:
  what / why it matters / what change would address it
- Load-bearing decisions validated: which big calls you back
- Load-bearing decisions to reconsider: which need more work
- Interface soundness: for each adjacent layer/concern
- Recommended changes: ordered by importance

Be rigorous but not destructive. If the stance is basically right,
say so and flag the few things to sharpen.
```

## Round 2 variant

For Round 2 Architect re-reviews, add at the top:

```
## Prior concerns to verify

The Round 1 Architect raised these concerns (A1-AN). Check whether
the Round 2 stance addresses each:

- A1: <verbatim concern>. Status in v2: <ADDRESSED / PARTIAL / IGNORED>
- ...
```

Round 2 Architect runs in parallel with Round 2 Critic — batch them
via `delegate_task(tasks=[...])`.
