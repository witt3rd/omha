# omha-deep-interview — Gaps vs OMC Reference

Identified by comparing our v1.0.0 against the actual OMC deep-interview
SKILL.md (650 lines) at /home/dt/src/ext/oh-my-claudecode/skills/deep-interview/SKILL.md

## Features to Add in v1.1

### High Value
1. **Ontology extraction** — OMC tracks entities (nouns) across rounds with stability ratios. When entities stabilize (same names, types, fields for 2+ rounds), the domain model has converged. This is a real signal, not just ambiguity scoring.
2. **Brownfield explore-first** — OMC uses an `explore` agent to scan the codebase BEFORE asking the user about it. "Never ask the user what the code already reveals." Our version asks the user about brownfield but doesn't explore autonomously.
3. **Execution bridge** — After spec confirmation, OMC offers: ralplan→autopilot (recommended), autopilot direct, ralph, team, or refine further. Our version just says "you can now use ralplan." Should actively offer choices.
4. **Non-goals section** in spec template — explicitly excluded scope, prevents scope creep during execution
5. **Assumptions Exposed & Resolved** table — tracks which assumptions were challenged and what was decided

### Medium Value
6. **Explicit scoring prompt** — OMC uses opus model at temperature 0.1 for scoring consistency with a detailed JSON prompt. Our version leaves scoring to the agent's judgment with a rubric. Could add a structured scoring prompt as a reference file.
7. **Rich progress display** — OMC shows a table with individual dimension scores, weights, weighted scores, and gaps per dimension. More informative than our simple coverage bin display.
8. **Full transcript in spec** — OMC includes the full interview Q&A as a collapsible `<details>` section in the spec. Our consensus plan chose synthesized-only, but having it as optional context could be valuable.

### Design Differences (Intentional)
- OMC uses float scores (0.0-1.0), we use coarse bins — our ralplan consensus chose bins deliberately
- OMC auto-detects brownfield, we ask — our consensus chose ask deliberately
- OMC has hard cap at round 20, we default to 5 — different design philosophy
- OMC uses challenge modes at fixed rounds (4/6/8), we use adaptive instruction — our consensus chose adaptive
- OMC auto-terminates at threshold, we require user confirmation — our consensus chose user-confirmed exit

## Priority for v1.1
Ontology extraction > explore-first > execution bridge > non-goals > assumptions table
