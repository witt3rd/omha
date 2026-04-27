# Orchestrator review template

Used when writing the orchestrator's final review (e.g.
`<orchestrator>-review.md`) — the honest assessment of the ralplan
output, before handing to the user.

This is the final quality gate. If what you write here feels weak,
the stance is not ready. Run another round, strengthen principles,
or fix the context package.

```markdown
# <Orchestrator>'s review of the <domain> ralplan output

**For:** <user>, when you read.
**From:** <orchestrator>
**Date:** <date>
**Stance file:** <path to stance.md> (read this *after* these notes)

---

## Does it meet my bar? Yes/No.

<One paragraph. If no, say why and what would make it yes.>

## What happened in the run

<Round tally. What the Critic caught that nobody else did. Concrete
naming of the moves that made the output good.>

## Where the stance ended up

<5-8 paragraphs. The dimensions, the load-bearing positions, what
was retired, the MV first shape. Enough that the user understands
the shape without having to read stance.md first.>

## Where I push back, gently

<4-6 items. Things you would raise when sitting together with the
user, but not things you would block on. Be specific, be
constructive.>

## Where I think the user will push back

<Your prediction of the user's questions before they see the stance.
This lets them walk in with priming. Be honest; if you don't know,
say so.>

## What this run proved about the method

<What worked. What would be tuned next run. What infrastructure
failures to debug separately (and where the handoff note lives).>

## Provisos folded during distillation (if any)

<If the Round 2 Critic returned APPROVE_WITH_PROVISO, list each
proviso here with a note on where it landed in the canonical stance.
Format:
- "Critic R2 PROVISO: <text>. Folded into §<section> as <treatment>."

This keeps provenance honest: the stance is the consensus product,
but this review records what was folded vs what was punted.>

## Summary for your review

<5-bullet summary. End with: "ready for your read." Or
not-ready-and-why.>

---

## Addendum: altitude

<If relevant: what this run demonstrates about the delegation-for-
vantage method itself. The first time a ralplan run goes well, the
addendum is often: "the stance is stronger than any proposal-correction
loop would have been, and the principles-as-guardrails worked." Note
when this fires; it's the value the orchestrator exists to deliver.>
```

## What makes a review honest vs performative

**Honest:**
- Names specific things the Critic caught that the orchestrator
  would have missed
- Names specific pushbacks the orchestrator has, with specific
  alternatives or the concession that they are not block-worthy
- Predicts user objections before they are raised
- Admits what the run taught the orchestrator about their own gaps

**Performative:**
- "Everything looks great" language
- Praise of the subagents without specifics
- No pushbacks (a perfect stance is almost always an unread stance)
- "I would have said the same thing" (you would not have, or the
  ralplan run was unnecessary)

## Length

~1500-3000 words typical. If under 1000, you didn't engage deeply.
If over 5000, you are re-writing the stance; stop.

## One discipline: read the stance twice before writing the review

First pass: does it meet the done-criteria in context.md?
Second pass: what would a skeptical user ask first?

The review is written against the second-pass mental state, not the
first. Compliance-checking is the Architect's job; the orchestrator's
review is about whether the work is *good*.
