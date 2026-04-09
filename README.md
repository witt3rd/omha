# Oh My Hermes (OMH)

Multi-agent orchestration skills for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Inspired by [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (OMC) and its ecosystem of community implementations, rebuilt natively for Hermes primitives.

## What This Is

OMH brings structured multi-agent workflows to Hermes through composable skills and an optional plugin that adds hook-based role injection, atomic state management, and evidence gathering. Skills work standalone with zero dependencies; the plugin (`plugins/omh/`) reduces boilerplate and enables token-efficient role injection.

| Skill | What It Does | Status |
|-------|-------------|--------|
| **omh-ralplan** | Consensus planning: Planner → Architect → Critic debate until agreement | Complete |
| **omh-deep-interview** | Socratic requirements interview with coverage tracking | Complete |
| **omh-ralph** | Verified execution: implement → verify → iterate until done | Complete |
| **omh-autopilot** | Full pipeline composing all three skills end-to-end | Complete |

## Origin Story

OMC solved a real problem: Claude Code's context window degrades over long sessions, and autonomous agents declare victory prematurely. OMC's answer was lifecycle hooks, 29 specialized agents, and mechanical stop-prevention — all tightly coupled to Claude Code's infrastructure.

OMH takes the best ideas from OMC and its community variants (Ouroboros, Huntley, Agentic Kit, and others published on the LobeHub Skills Marketplace) and rebuilds them for Hermes using only three primitives:

- **`delegate_task`** — Isolated subagents with role-specific context (fresh context per agent, no history leakage)
- **File-based state** — `.omh/` directory for persistence, handoffs, and resumability
- **Skills** — Markdown instructions the agent follows, in the `agentskills.io` open standard

The key architectural insight came during the ralph consensus process: instead of fighting Hermes's lack of a stop-prevention hook, we lean into the "one-task-per-invocation" pattern — each ralph call does one unit of work, updates state, and exits. The caller re-invokes. This is actually more faithful to Geoffrey Huntley's original ralph concept (`while :; do cat PROMPT.md | claude-code; done`) than OMC's in-session loop.

## Install

```bash
# Add the tap (one-time)
hermes skills tap add witt3rd/oh-my-hermes

# Install individual skills
hermes skills install omh-ralplan
hermes skills install omh-deep-interview
hermes skills install omh-ralph
hermes skills install omh-autopilot
```

Or install manually by copying `skills/<name>/` to `~/.hermes/skills/omh/`.

## How They Compose

```
omh-deep-interview  →  confirmed spec (.omh/specs/)
        ↓
omh-ralplan         →  consensus plan (.omh/plans/)
        ↓
omh-autopilot       →  detects existing spec/plan, skips completed phases
        ↓ (internally uses)
omh-ralph           →  one-task-per-invocation until verified complete
```

Each skill works standalone. Autopilot composes them into a pipeline but any skill can be used independently:

- **Just need a plan?** → `omh-ralplan`
- **Vague idea?** → `omh-deep-interview` → `omh-ralplan`
- **Have a plan, need execution?** → `omh-ralph`
- **End-to-end?** → `omh-autopilot`

## Core Concepts

### Consensus Planning (Ralplan)

Three perspectives debate until they agree:

```
Planner drafts a plan
    → Architect reviews for structural soundness
    → Critic challenges assumptions adversarially
    → If not all APPROVE: Planner revises, loop back (max 3 rounds)
    → Consensus reached: plan written to .omh/plans/
```

This catches blind spots that a single agent misses. The Critic's job is to break the plan — if it survives, it's stronger for it.

### Requirements Interview (Deep Interview)

A Socratic conversation that gates on user-confirmed readiness, not automated scoring:

- Asks one targeted question per round, focused on the weakest dimension
- Tracks coverage across four dimensions: Goal, Constraints, Success Criteria, Existing Context
- Uses coarse bins (HIGH/MEDIUM/LOW/CLEAR) as heuristics, never as exit gates
- The user always decides when they're done — scoring never auto-terminates
- Outputs a confirmed spec that downstream skills consume

Design decisions made during consensus review:
- Coarse bins over float scores (LLM self-assessment lacks decimal precision)
- User-confirmed exit over threshold-gated exit (the user is the authority)
- Ask about brownfield, don't auto-detect (respects user knowledge)
- Adaptive questioning over named challenge modes (simpler, same effect)

### Verified Execution (Ralph)

One-task-per-invocation persistence:

```
Read state → Pick next task → Execute (delegate_task with executor role)
    → Verify (orchestrator runs builds/tests, then delegate_task with verifier role)
    → Update state → Exit
    → Caller re-invokes for next task
```

Key mechanisms:
- **Planning gate**: Won't execute without a spec or plan with acceptance criteria
- **Separation of concerns**: Executor writes code, verifier checks evidence (read-only), architect reviews holistically
- **3-strike circuit breaker**: Same error fingerprint 3 times → stop and surface the fundamental issue
- **Cancel signal**: `.omh/state/ralph-cancel.json` with 30-second TTL for clean abort
- **Learnings forward**: Completed task discoveries feed into subsequent executor context
- **Parallel-first**: Independent tasks batch up to 3 concurrent subagents

### Full Pipeline (Autopilot)

Composes all skills into phases, detecting existing artifacts to skip completed work:

```
Phase 0: Requirements  → deep-interview (skip if .omh/specs/ has confirmed spec)
Phase 1: Planning      → ralplan consensus (skip if .omh/plans/ has approved plan)
Phase 2: Execution     → ralph persistence loop
Phase 3: QA            → build + test cycling
Phase 4: Validation    → parallel review (architect + security + code reviewer)
Phase 5: Cleanup       → delete state files, report summary
```

## Key Adaptations from OMC

| OMC Pattern | OMH Adaptation | Why |
|---|---|---|
| `spawn_agent` with role prompts | `[omh-role:NAME]` marker in goal; `pre_llm_call` hook injects role prompt into subagent system prompt only | Parent context never loads role text — zero token overhead in the parent session |
| `persistent-mode.cjs` (mechanical stop prevention) | One-task-per-invocation + state files | Hermes has no stop hook; state-based resumability is more robust than prompt-based persistence |
| 6 concurrent child agents | 3 concurrent (Hermes `MAX_CONCURRENT_CHILDREN`) | Batch into groups of 3; Phase 4 validation fits exactly |
| Float ambiguity scores (0.0-1.0) with auto-exit gate | Coarse bins (HIGH/MEDIUM/LOW/CLEAR) with user-confirmed exit | LLM self-assessment lacks the precision to justify decimal thresholds |
| PRD user stories (`prd.json`) | Task items from ralplan consensus plans | Equivalent structure, different source |
| `.omc/` state directory | `.omh/` state directory | Same convention, different namespace |
| Haiku/Sonnet/Opus tier routing | Default model with per-subagent override | Hermes delegate_task supports model param but doesn't auto-route |
| Challenge modes (Contrarian/Simplifier/Ontologist) | Single adaptive instruction | Same effect, less ceremony |
| `AskUserQuestion` (clickable UI) | Conversational questions | Hermes is platform-agnostic (CLI, Telegram, etc.) |
| Deslop pass (mandatory in ralph) | Deferred to autopilot | Scope reduction for v1; documented as known gap |

## Role Prompts

Eight shared role prompts give subagents precise behavioral instructions:

| Role | Purpose | Used By |
|------|---------|---------|
| **Planner** | Task decomposition, sequencing, risk flags | ralplan |
| **Architect** | Structural review, boundary clarity, long-term maintainability | ralplan, ralph (final review) |
| **Critic** | Adversarial challenge, assumption testing, stress testing | ralplan |
| **Executor** | Code implementation, test-first, minimal changes | ralph |
| **Verifier** | Evidence-based completion checking, read-only, pass/fail | ralph |
| **Analyst** | Requirements extraction, hidden constraints, acceptance criteria | deep-interview, autopilot |
| **Security Reviewer** | Vulnerabilities, trust boundaries, injection vectors | autopilot (validation phase) |
| **Test Engineer** | Test strategy, coverage, edge cases, flaky test hardening | autopilot (QA phase) |
| **Debugger** | Root cause analysis, hypothesis testing, minimal targeted fixes | ralph (error diagnosis) |

### How Role Injection Works (v2 Plugin)

With the v2 plugin installed, skills use `[omh-role:NAME]` markers in the `delegate_task` goal string instead of embedding role prompt text inline:

```python
# In skill prose — no role file loading, no context pollution:
delegate_task(
    goal="[omh-role:executor] Implement the following task:\n\n<task>...",
    context="<project context only>"
)
```

The Hermes `pre_llm_call` hook fires at the start of each subagent session, detects the marker in `user_message` (which equals the `goal` string), loads the matching role file from `plugins/omh/references/role-{name}.md`, and injects it into the subagent's system prompt via `{"context": ...}`. The role text never passes through the parent agent's context window.

A `pre_tool_call` hook validates `[omh-role:NAME]` markers before the subagent starts, warning immediately on unknown role names (fail-fast for typos).

**Fallback**: `omh_state(action="load_role", role="NAME")` returns the role prompt as a string for skills that need it explicitly.

**Debug mode**: Set `OMH_DEBUG=1` (env var) or `debug: true` in `config.yaml` to see injection events:
```
[OMH DEBUG] pre_tool_call: delegate_task with role 'executor' detected
[OMH DEBUG] pre_llm_call: injecting role 'executor' into subagent system prompt
```

## State Convention

All state lives in `.omh/` within the project directory:

```
.omh/
├── state/                              # Active mode state (JSON)
│   ├── interview-{id}.json             # Active deep-interview session
│   ├── ralph-state.json                # Active ralph session
│   ├── ralph-tasks.json                # Task tracking for ralph
│   ├── ralph-cancel.json               # Cancel signal (30s TTL)
│   └── autopilot-state.json            # Active autopilot session
├── plans/                              # Consensus plans (Markdown, persisted)
│   └── ralplan-{name}-consensus.md
├── specs/                              # Interview specs (Markdown, persisted)
│   └── {project}-spec.md
├── logs/                               # Audit trail
│   ├── interview-{id}.log
│   └── ralph-{id}.log
└── progress/                           # Append-only execution logs
    └── ralph-progress.md
```

State files are deleted on successful completion. Specs and plans persist as artifacts.

## Methodology: Self-Bootstrapping

OMH was built using its own tools. The first skill implemented was `omh-ralplan` (consensus planning), which was then used to design the remaining skills through multi-agent debate:

1. **omh-deep-interview** — Designed via ralplan consensus (2 rounds: Planner drafted, Critic challenged scoring-as-exit-gate and undefined spec contract, Planner revised, both approved)
2. **omh-ralph** — Designed via ralplan consensus with OMC source + LobeHub references fed to all subagents (2 rounds: both reviewers demanded cancel mechanism, context strategy, and verifier separation; Critic proposed one-task-per-invocation architecture; Planner adopted it; both approved)

Each consensus process produced a plan that was then reviewed against the actual OMC source code and LobeHub marketplace implementations, ensuring OMH preserves the patterns that matter while adapting to Hermes's architecture.

## Reference Material

The `docs/` directory contains analysis of the source implementations:

| Document | Contents |
|----------|----------|
| `docs/architecture.md` | OMH composition model, primitives, constraints |
| `docs/omc-ralph-reference.md` | Extracted from actual OMC source: ralph, ultrawork, autopilot, persistent-mode.cjs, agent prompts, 12 design patterns |
| `docs/lobehub-skills-reference.md` | 3 ralph variants, 2 deep-interview implementations, 2 autopilot implementations from the LobeHub marketplace |

## Requirements

- Hermes Agent v0.7.0+
- **Skills only**: No additional dependencies — copy skill directories to `~/.hermes/skills/omh/`
- **With plugin**: Python 3.10+; `pyyaml` optional (graceful fallback to empty config); install `plugins/omh/` to `~/.hermes/plugins/omh/`

### Development

To run the plugin test suite:

```bash
pip install -e ".[dev]"
python -m pytest plugins/omh/tests/
```

## Hermes Constraints

| Constraint | Impact | How OMH Handles It |
|---|---|---|
| 3 concurrent subagents | Can't fire 6 parallel agents like OMC | Batch into groups of 3; validation phase fits exactly |
| No recursive delegation | Subagents can't spawn subagents | All orchestration at top level; subagents are leaf workers |
| No stop-prevention hook | Can't mechanically force continuation | One-task-per-invocation + state files for ralph; prompt-based for ralplan |
| Subagents lack `execute_code` | Children reason step-by-step | Orchestrator handles batch operations; subagents use tools directly |
| Subagents lack `memory` | Children can't write to shared memory | State passed via files and delegate_task context |

## What's Missing (Honest Gaps)

OMH v1.0 replicates the core execution pipeline (~85%) but not the full OMC feature surface (~60% overall). Here's what we don't do.

### Can't Do With Skills Alone

These require Hermes code changes or plugins:

| Gap | What OMC Has | Why We Can't | Path Forward |
|-----|-------------|-------------|--------------|
| **Stop prevention** | `persistent-mode.cjs` — 1144 lines that mechanically block Claude Code from exiting | Hermes has no `Stop` lifecycle hook. Skills can instruct but can't enforce. | PR: `pre_session_end` veto hook. Our workaround: state files + re-invocation. |
| **LSP integration** | 12 IDE-grade tools (hover, references, rename, diagnostics) | Not a skill-level feature — requires tool registration or MCP server. | PR or MCP server package. We use terminal-based tools (ripgrep, linters). |
| **ast-grep** | Structural code search/replace using AST matching | Same — needs tool registration. | Terminal fallback: `ast-grep` CLI works if installed. |
| **HUD / observability** | Real-time statusline with token tracking, agent activity | No display API in Hermes skills. | Plugin using `post_tool_call` hook. We use `todo` + progress logs. |
| **Rate limit auto-resume** | `omc wait` daemon monitors for resets | No equivalent daemon mechanism. | Hermes has credential pool rotation, which handles most cases. |

### Haven't Built Yet (Could Be Skills)

| Gap | What OMC Has | Priority | Effort |
|-----|-------------|----------|--------|
| **19 more agent roles** | designer, qa-tester, scientist, git-master, tracer, vision, product-manager, ux-researcher, etc. We have 10 of OMC's 29. | Medium | Low per role — add as needed |
| **Deslop pass** | `ai-slop-cleaner` as mandatory post-process in ralph | Medium | New skill |
| **Model tier routing** | Auto-routes Haiku/Sonnet/Opus by task complexity. We use one model for all. | Low-Medium | Routing logic in autopilot |
| **Ontology extraction** | Tracks entities across interview rounds with stability ratios | Medium-High | Deep-interview v1.1 |
| **Brownfield explore-first** | Scans codebase before asking the user | Medium | Deep-interview v1.1 |
| **Team mode** | Native agent teams with direct inter-agent messaging | Low | Fundamental architecture difference — Hermes subagents are isolated |
| **Multi-model orchestration** | Claude + Codex + Gemini workers via tmux | Low | Niche; ACP transport partially addresses |

### Deliberate Design Differences

These aren't gaps — they're choices made during consensus review:

| OMC Does | OMH Does | Why |
|----------|-----------|-----|
| Float ambiguity scores (0.0-1.0) with auto-exit | Coarse bins (HIGH/MEDIUM/LOW/CLEAR), user-confirmed exit | LLM self-assessment lacks decimal precision. The user is the authority on readiness. |
| In-session persistence loop | One-task-per-invocation + state files | Hermes can't prevent exit mechanically. State-based resume is more robust and eliminates context exhaustion. |
| Auto-detect brownfield | Ask the user | Checking for `package.json` etc. is unreliable and presumptuous. |
| 3 named challenge modes at fixed rounds | Single adaptive instruction | Same effect, less ceremony. Consensus review called the modes "cargo cult." |
| Full interview transcript in spec | Synthesized summary only | Keeps specs readable and focused. Full transcript is ephemeral. |

## Roadmap

```
v1.0:           Skills only — verbose but functional, zero dependencies
v2.0 (current): Hermes plugin — infrastructure layer with hook-based role injection
v3.0 (future):  Upstream PR to NousResearch/hermes-agent optional-skills/
```

### v2.0: The Plugin Layer (Shipped)

The v2 plugin (`plugins/omh/`) is installed at `~/.hermes/plugins/omh/` and registers custom tools and hooks that eliminate the infrastructure plumbing from skill prose:

| Component | What It Does | Status |
|-----------|-------------|--------|
| `omh_state` tool (8 actions) | Atomic read/write/check/cancel for `.omh/` state files; `load_role` action for explicit role loading | Shipped |
| `omh_gather_evidence` tool | Runs build/test/lint commands from an allowlist, captures + truncates output | Shipped |
| `pre_llm_call` hook | Detects `[omh-role:NAME]` in subagent `user_message`; injects matching role prompt into system context | Shipped |
| `pre_tool_call` hook | Validates `[omh-role:NAME]` markers in `delegate_task` goals before subagents start; warns on unknown roles | Shipped |
| `on_session_end` hook | Writes `_interrupted_at` to active mode state on unexpected exit | Shipped |
| Model tier routing | Maps roles to Haiku/Sonnet/Opus via config | Roadmap |

The key architectural insight for role injection: `delegate_task` passes `goal` as `user_message` to the subagent's `run_conversation()`. The `pre_llm_call` hook receives this as `user_message` on `is_first_turn=True`, making it the natural injection point — no new Hermes primitives required.

Skills express intent instead of mechanism. Compare v1 vs v2 delegation:

```markdown
# v1 skill prose (verbose — role text inlined, state loaded manually)
Load the executor role from ~/.hermes/skills/omh-ralplan/references/role-executor.md
and pass it in the context field of delegate_task alongside the task definition...

# v2 skill prose (concise — hook handles injection)
delegate_task(goal="[omh-role:executor] Implement: {task}", context="{project context}")
```

## Distribution

OMH is distributed as a GitHub tap for the Hermes Skills Hub:

```bash
hermes skills tap add witt3rd/oh-my-hermes
hermes skills install omh-ralplan
```

## License

MIT
