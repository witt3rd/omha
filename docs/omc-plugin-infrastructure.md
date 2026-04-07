# OMC Plugin Infrastructure — Mechanical Layer Analysis

Source: `/home/dt/src/ext/oh-my-claudecode/`
Total lines analyzed: ~12,300 across 31 files
Generated: 2026-04-07

---

## Overview

OMC's "skills" are markdown instructions (e.g., `$ralph`, `$autopilot`). What makes
them WORK is a mechanical layer of TypeScript code that:

1. **HOOKS** — intercept Claude Code lifecycle events (Stop, PreToolUse, PostToolUse,
   UserPromptSubmit) and inject continuation prompts or block stops
2. **STATE MANAGEMENT** — persist mode state to disk with atomic writes, session
   isolation, and legacy migration
3. **MODEL ROUTING** — score task complexity and route sub-agent delegations to
   haiku/sonnet/opus
4. **DELEGATION** — resolve which provider/tool to use, enforce model parameters,
   and categorize tasks with temperature/thinking budget

---

## 1. HOOKS SUBSYSTEM

### Architecture

```
Shell Hook Scripts (bash)
  └─> bridge.ts (2,421 lines) — main entry point, routes events to handlers
        ├─> keyword-detector/ — detects skill invocation keywords in user input
        ├─> persistent-mode/index.ts (1,310 lines) — THE core enforcement engine
        │     ├─> ralph/loop.ts — ralph state machine
        │     ├─> ralph/verifier.ts — architect verification protocol
        │     ├─> autopilot/enforcement.ts — autopilot phase enforcement
        │     ├─> ultrawork/ — ultrawork reinforcement
        │     └─> todo-continuation/ — baseline todo enforcement
        └─> omc-orchestrator/ — pre/post tool use orchestration
```

### 1.1 Persistent Mode Hook (`src/hooks/persistent-mode/index.ts`)

**Lines:** 1,310
**What it does:** This is the CORE enforcement engine. It intercepts every `Stop` event
and decides whether to block it (injecting a continuation prompt) or allow the session
to end.

**Main entry point:** `checkPersistentModes(sessionId?, directory?, stopContext?)`

**Algorithm — Priority-ordered mode checking:**

```
1. BYPASS CHECKS (always allow stop):
   - isCriticalContextStop() — context window >= 95% full, or explicit context-limit
   - isExplicitCancelCommand() — user ran /cancel
   - isSessionCancelInProgress() — cancel signal file exists and not expired (30s TTL)
   - isUserAbort() — user explicitly aborted
   - isRateLimitStop() — API returned 429
   - isAuthenticationError() — 401/403 errors

2. MODE CHECKS (in priority order):
   Priority 1:   checkRalphLoop() — ralph persistence loop
   Priority 1.5: checkAutopilot() — autopilot phase enforcement
   Priority 1.7: checkTeamPipeline() — standalone team mode
   Priority 1.8: checkRalplan() — consensus planning
   Priority 2:   checkUltrawork() — ultrawork reinforcement
   Priority 3:   checkSkillActiveState() — active skill enforcement
```

**Output contract:**
```typescript
interface PersistentModeResult {
  shouldBlock: boolean;    // true = inject message and keep working
  message: string;         // continuation prompt injected into context
  mode: 'ralph' | 'ultrawork' | 'autopilot' | 'team' | 'ralplan' | 'none';
  metadata?: { iteration, maxIterations, phase, toolError, ... };
}
```

**Hook output:** `continue: !result.shouldBlock` — when shouldBlock=true, returns
`continue: false` to hard-block the stop event.

**State files managed:**
- Cancel signal: `.omc/state/sessions/{sessionId}/cancel-signal.json`
- Tool errors: `.omc/state/last-tool-error.json`
- Idle notifications: `.omc/state/sessions/{sessionId}/idle-notif-cooldown.json`

**Key safety mechanisms:**
- Session isolation: every mode check validates `state.session_id === sessionId`
- Stale state detection: states older than 2 hours are ignored
- Cancel signal TTL: 30 seconds, auto-cleaned on expiry
- Tool error staleness: errors older than 60s are ignored
- Circuit breakers: team/ralplan have max reinforcement counts (20/30) with TTLs
- Todo continuation: max 5 attempts per session before giving up

### 1.2 Ralph Hook (`src/hooks/ralph/`)

**Total lines:** 1,972 across 5 files
**What it does:** Implements a self-referential work loop that continues until
explicitly cancelled or architect-verified complete.

#### loop.ts (539 lines) — State machine

**State schema:**
```typescript
interface RalphLoopState {
  active: boolean;
  iteration: number;           // Current iteration (starts at 1)
  max_iterations: number;      // Default 10, auto-extends by 10 at limit
  started_at: string;          // ISO timestamp
  prompt: string;              // Original task
  session_id?: string;
  project_path?: string;
  prd_mode?: boolean;          // Whether PRD tracking is active
  current_story_id?: string;
  linked_ultrawork?: boolean;  // Auto-activates ultrawork alongside ralph
  critic_mode?: 'architect' | 'critic' | 'codex';
}
```

**Key behaviors:**
- `createRalphLoopHook()` — factory that returns startLoop/cancelLoop/getState
- `startLoop()` checks mutual exclusion with UltraQA, writes state, auto-activates
  ultrawork (linked), auto-enables PRD mode if prd.json exists
- `cancelLoop()` clears both ralph and linked ultrawork state
- Iteration limits auto-extend: when `iteration >= max_iterations`, extends by 10
  (unless hard max from security config is reached)
- PRD integration: reads prd.json, tracks current story, injects next story context
- Supports `--no-prd` and `--critic=<mode>` flags parsed from prompt text

#### prd.ts (438 lines) — Product Requirements Document

**PRD schema:**
```typescript
interface PRD {
  project: string;
  branchName: string;
  description: string;
  userStories: UserStory[];  // Each has id, title, description, acceptanceCriteria, priority, passes
}
```

**Algorithm for completion:**
- Stories sorted by priority (ascending)
- Completion = all stories have `passes: true`
- Next story = highest priority (lowest number) with `passes: false`

**File locations:** `{project}/prd.json` or `{project}/.omc/prd.json`

#### verifier.ts (333 lines) — Architect verification protocol

**Flow:**
1. Ralph claims completion → `startVerification()` creates VerificationState
2. Persistent mode hook detects pending verification → injects verification prompt
3. Prompt instructs agent to spawn architect/critic/codex reviewer
4. Hook reads session transcript tail (last 32KB) for approval/rejection markers
5. Approval detected via regex: `<ralph-approved ...>VERIFIED_COMPLETE</ralph-approved>`
6. Rejection detected via heuristic patterns (6 regex patterns)
7. On approval: clears all state, allows stop
8. On rejection: records feedback, injects continuation prompt
9. Max 3 verification attempts before force-accepting

**State schema:**
```typescript
interface VerificationState {
  pending: boolean;
  completion_claim: string;
  verification_attempts: number;      // Incremented on each feedback
  max_verification_attempts: number;  // Default 3
  architect_feedback?: string;
  architect_approved?: boolean;
  requested_at: string;
  original_task: string;
  critic_mode?: 'architect' | 'critic' | 'codex';
}
```

#### progress.ts (511 lines) — Memory persistence

**Append-only text log** (progress.txt) with:
- Codebase Patterns section (consolidated learnings at top)
- Per-story progress entries (timestamp, storyId, implementation, files, learnings)
- Parsed via line-by-line state machine (inPatterns → entry → sections)
- Learnings deduplicated on context injection
- Recent 5 entries used for context

### 1.3 Autopilot Hook (`src/hooks/autopilot/`)

**Total lines:** 2,191 across 5 files
**What it does:** Full autonomous execution pipeline from idea to working code.

#### state.ts (644 lines) — Phase state machine

**Phases:** `expansion → planning → execution → qa → validation → complete/failed`

**State schema:**
```typescript
interface AutopilotState {
  active: boolean;
  phase: AutopilotPhase;
  iteration: number;
  max_iterations: number;      // Safety limit
  originalIdea: string;
  expansion: { analyst_complete, architect_complete, spec_path, ... };
  planning: { plan_path, architect_iterations, approved };
  execution: { ralph_iterations, ultrawork_active, tasks_completed, ... };
  qa: { ultraqa_cycles, build_status, lint_status, test_status };
  validation: { architects_spawned, verdicts, all_approved, ... };
  started_at, completed_at, phase_durations, total_agents_spawned;
  session_id, project_path;
}
```

**Phase transitions with rollback:**
- `transitionRalphToUltraQA()` — 5-step process with rollback on failure:
  1. Save ralph progress to autopilot state
  2. Deactivate ralph (set active=false, keep file for rollback)
  3. Transition autopilot to QA phase
  4. Start UltraQA
  5. On success: clear ralph. On failure: restore ralph and execution phase
- Mutual exclusion via `canStartMode()` from mode-registry

#### enforcement.ts (555 lines) — Signal detection

**Signal detection:** Reads session transcript files looking for literal strings:
```
EXPANSION_COMPLETE, PLANNING_COMPLETE, EXECUTION_COMPLETE,
QA_COMPLETE, VALIDATION_COMPLETE, AUTOPILOT_COMPLETE
```

**Legacy enforcement:** Phase → expected signal → detect in transcript → transition
**Pipeline enforcement:** Uses pipeline orchestrator for stage-based transitions

**Awaiting confirmation:** 2-minute TTL on `awaiting_confirmation` flag prevents
re-enforcement while user is being asked to confirm.

#### pipeline.ts (555 lines) — Configurable pipeline

**Stage order:** `RALPLAN → EXECUTION → RALPH → QA`

**Pipeline tracking state:**
```typescript
interface PipelineTracking {
  pipelineConfig: PipelineConfig;
  stages: PipelineStageState[];     // Each has id, status, iterations, startedAt, ...
  currentStageIndex: number;
}
```

**Each stage:** `pending → active → complete/failed/skipped`
**Stage adapters:** Each stage has `shouldSkip()`, `getPrompt()`, `completionSignal`,
optional `onEnter()`/`onExit()` lifecycle hooks.
**Advancement:** `advanceStage()` marks current complete, finds next non-skipped,
activates it, calls lifecycle hooks.

### 1.4 Hook Bridge (`src/hooks/bridge.ts`)

**Lines:** 2,421
**What it does:** Shell entry point that routes Claude Code hook events to TypeScript handlers.

**Event types handled:**
- `UserPromptSubmit` — keyword detection, skill invocation, mode activation
- `Stop` — persistent mode enforcement (calls checkPersistentModes)
- `PreToolUse` — model enforcement (delegation-enforcer), permission handling,
  tool blocking (pkill -f, dangerous commands)
- `PostToolUse` — error tracking, agent dashboard updates, rules injection,
  session replay recording
- `SubagentStart/Stop` — agent lifecycle tracking
- `PreCompact` — pre-compaction hook
- `SessionEnd` — cleanup

**Hot path optimization:** Keyword detector, orchestrator hooks, and subagent tracker
are eagerly imported. Heavy modules (learner, wiki, recovery) are lazy-imported.

---

## 2. STATE MANAGEMENT SUBSYSTEM

### Architecture

```
State Manager (features/state-manager/)
  └─> Unified API with local/global/legacy support + caching
        └─> atomic-write.ts — temp-file + rename pattern
              └─> mode-state-io.ts — mode-specific read/write/clear
                    └─> worktree-paths.ts — git worktree-aware path resolution

Boulder State (features/boulder-state/)
  └─> Plan tracking with file-lock-protected multi-session access
```

### 2.1 State Manager (`src/features/state-manager/index.ts`)

**Lines:** 818 (index) + 158 (types) = 976
**What it does:** Unified state file management with caching, legacy migration,
and cleanup.

**State locations:**
- LOCAL: `.omc/state/{name}.json` (resolved from git worktree root)
- GLOBAL: XDG-aware user OMC state dir (with `~/.omc/state` fallback)

**Read cache:**
```typescript
// 5-second TTL, max 200 entries, mtime-validated
// TOCTOU-safe: reads mtime BEFORE file read, verifies AFTER
const STATE_CACHE_TTL_MS = 5_000;
const MAX_CACHE_SIZE = 200;
interface CacheEntry { data: unknown; mtime: number; cachedAt: number; }
```

**Read algorithm:**
1. Check standard path, get mtime before read
2. Check cache: same mtime + within TTL → return cached clone
3. Cache miss: readFileSync + JSON.parse
4. Verify mtime unchanged after read → cache only if stable
5. On miss: try legacy paths (LEGACY_LOCATIONS map)
6. Return `{ exists, data, foundAt, legacyLocations }`

**Write:** Always to standard location, invalidates cache, uses `atomicWriteJsonSync`

**Migration:** Reads from legacy location → writes to standard → deletes legacy

**Cleanup:** `cleanupOrphanedStates()` removes files not modified in N days (default 30)

**Max state age:** 4 hours (`MAX_STATE_AGE_MS`)

### 2.2 Mode State I/O (`src/lib/mode-state-io.ts`)

**Lines:** 247
**What it does:** Canonical read/write/clear for mode state files with session
isolation and ghost-legacy cleanup.

**Write envelope:**
```typescript
{
  ...state,
  _meta: { written_at: ISO_timestamp, mode: "ralph", sessionId?: "..." }
}
```
- Files written with mode 0o600 (owner-only)
- Directories auto-created via `ensureSessionStateDir()` / `ensureOmcDir()`

**Read:** Strips `_meta` envelope so callers get clean state. Session-scoped reads
have NO legacy fallback (prevents cross-session leakage).

**Clear (ghost-legacy cleanup):**
- With sessionId: deletes session-scoped file + legacy files owned by this session
- Without sessionId: deletes all legacy candidates + all session directories
- Ownership check: `canClearStateForSession()` reads `_meta.sessionId` or
  `state.session_id`

**Session path resolution:**
```
.omc/state/sessions/{sessionId}/{mode}-state.json   (session-scoped)
.omc/state/{mode}-state.json                         (legacy global)
```

**Cross-session state recovery:** `findSessionOwnedStateFiles()` scans ALL session
directories for files whose embedded owner matches the requested session (handles
session continuation/manual recovery).

### 2.3 Atomic Write (`src/lib/atomic-write.ts`)

**Lines:** 262
**What it does:** Crash-safe file writes using temp-file + atomic rename.

**Algorithm (sync and async variants):**
```
1. ensureDirSync(parent directory)
2. Open temp file with O_CREAT | O_EXCL | O_WRONLY, mode 0o600
3. Write content
4. fsync(fd)          — flush to disk
5. close(fd)
6. rename(temp, target)  — atomic replace
7. fsync(directory)   — best-effort, ensure rename is durable
8. On error: unlink temp file
```

**Temp file naming:** `.{basename}.tmp.{crypto.randomUUID()}`

**Three variants:**
- `atomicWriteJson(path, data)` — async, JSON
- `atomicWriteJsonSync(path, data)` — sync, JSON
- `atomicWriteSync(path, content)` / `atomicWriteFileSync(path, content)` — sync, text

### 2.4 Boulder State (`src/features/boulder-state/`)

**Lines:** 310 across 3 files
**What it does:** Tracks the active work plan across sessions.

**State schema:**
```typescript
interface BoulderState {
  active_plan: string;        // Path to the .md plan file
  started_at: string;
  session_ids: string[];      // Multiple sessions can reference same plan
  plan_name: string;
  active: boolean;
  updatedAt: string;
}
```

**Multi-session safety:** `appendSessionId()` uses file-level locking
(`withFileLockSync()`) to safely append session IDs from concurrent processes.

**Plan progress parsing:** Reads markdown files and counts checkboxes:
```
/^[-*]\s*\[\s*\]/gm   → unchecked
/^[-*]\s*\[[xX]\]/gm  → checked
```

---

## 3. MODEL ROUTING SUBSYSTEM

### Architecture

```
routeTask(context, config)
  ├─> extractAllSignals(prompt, context) → ComplexitySignals
  │     ├─> extractLexicalSignals()   → word count, keywords, question depth
  │     ├─> extractStructuralSignals() → subtasks, cross-file, impact, domain
  │     └─> extractContextSignals()   → failures, chain depth, plan complexity
  ├─> evaluateRules(context, signals) → first matching rule wins
  ├─> calculateComplexityScore(signals) → weighted numeric score
  └─> Reconcile rule result with score → final tier + confidence
```

**Lines:** 1,626 across 6 files

### 3.1 Signal Extraction (`signals.ts`, 323 lines)

**Lexical signals** (from prompt text):
- `wordCount` — raw word count
- `filePathCount` — regex for paths with `/` or `\`
- `codeBlockCount` — triple backtick blocks
- `hasArchitectureKeywords` — 10 keywords (refactor, redesign, decouple, ...)
- `hasDebuggingKeywords` — 10 keywords (debug, root cause, investigate, ...)
- `hasSimpleKeywords` — 10 keywords (find, search, list, show, ...)
- `hasRiskKeywords` — 10 keywords (critical, production, security, migration, ...)
- `questionDepth` — hierarchy: why > how > what > where > none
- `hasImplicitRequirements` — statements without clear deliverables

**Structural signals** (from prompt parsing):
- `estimatedSubtasks` — count bullet points, numbered items, "then/and/also" connectors
- `crossFileDependencies` — 2+ file paths mentioned
- `hasTestRequirements` — test-related keywords
- `domainSpecificity` — generic/frontend/backend/infrastructure/security
- `requiresExternalKnowledge` — API/SDK/library references
- `reversibility` — easy/moderate/difficult (based on keywords)
- `impactScope` — local/module/system-wide

**Context signals** (from session state):
- `previousFailures`, `conversationTurns`, `planComplexity`,
  `remainingTasks`, `agentChainDepth`

### 3.2 Scoring (`scorer.ts`, 287 lines)

**Weighted scoring system:**
```
TIER THRESHOLDS:
  Score >= 8 → HIGH (Opus)
  Score >= 4 → MEDIUM (Sonnet)
  Score <  4 → LOW (Haiku)

WEIGHTS:
  Lexical:
    wordCount > 200: +2, > 500: +1 additional
    2+ file paths: +1
    code blocks: +1
    architecture keywords: +3
    debugging keywords: +2
    simple keywords: -2
    risk keywords: +2
    question depth 'why': +2, 'how': +1
    implicit requirements: +1

  Structural:
    subtasks > 3: +3, > 1: +1
    cross-file: +2
    test required: +1
    security domain: +2, infrastructure: +1
    external knowledge: +1
    reversibility difficult: +2, moderate: +1
    impact system-wide: +3, module: +1

  Context:
    per previous failure: +2 (max +4)
    agent chain depth >= 3: +2
    plan complexity >= 5: +1
```

**Confidence calculation:**
```
confidence = 0.5 + (min(distanceFromNearestThreshold, 4) / 4) * 0.4
Range: 0.5 (at threshold) to 0.9 (4+ points away from threshold)
```

### 3.3 Rules Engine (`rules.ts`, 285 lines)

**20 rules, priority-ordered (100 → 0), first match wins:**

| Priority | Rule | Tier |
|----------|------|------|
| 100 | explicit-model-specified | EXPLICIT |
| 85 | architect-complex-debugging | HIGH |
| 80 | architect-simple-lookup | LOW |
| 75 | planner-simple-breakdown | LOW |
| 75 | planner-strategic-planning | HIGH |
| 75 | critic-checklist-review | LOW |
| 75 | critic-adversarial-review | HIGH |
| 75 | analyst-simple-impact | LOW |
| 75 | analyst-risk-analysis | HIGH |
| 70 | architecture-system-wide | HIGH |
| 70 | security-domain | HIGH |
| 70 | difficult-reversibility-risk | HIGH |
| 65 | deep-debugging | HIGH |
| 60 | complex-multi-step | HIGH |
| 60 | simple-search-query | LOW |
| 55 | short-local-change | LOW |
| 50 | moderate-complexity | MEDIUM |
| 45 | module-level-work | MEDIUM |
| 0 | default-medium | MEDIUM |

**Rule structure:**
```typescript
interface RoutingRule {
  name: string;
  condition: (context: RoutingContext, signals: ComplexitySignals) => boolean;
  action: { tier: ComplexityTier; reason: string };
  priority: number;
}
```

### 3.4 Router (`router.ts`, 348 lines)

**Routing algorithm:**
1. If `forceInherit` → return 'inherit' (agents use parent model)
2. If routing disabled → use defaultTier
3. If explicit model → bypass routing
4. If agent-specific override → use override
5. Extract signals → evaluate rules → calculate score
6. Reconcile: if rules and scorer diverge by >1 level, reduce confidence
   to 0.5 and prefer the HIGHER tier (avoid under-provisioning)
7. Enforce minTier if configured

**Escalation:** `LOW → MEDIUM → HIGH` (deprecated — orchestrator routes proactively)

**Quick tier lookup:** Static agent→tier map for known agents without full analysis:
```
architect, planner, critic, analyst → HIGH
explore, writer → LOW
executor, test-engineer, designer → MEDIUM
```

**Model mapping:** `LOW → haiku, MEDIUM → sonnet, HIGH → opus`
(configurable via env vars: OMC_MODEL_HIGH, OMC_MODEL_MEDIUM, OMC_MODEL_LOW)

---

## 4. DELEGATION SUBSYSTEM

### Architecture

```
PreToolUse event
  └─> delegation-enforcer.ts — intercepts Task/Agent tool calls
        ├─> enforceModel() — inject/normalize model parameter
        ├─> delegation-routing/resolver.ts — resolve provider/tool
        └─> delegation-categories/index.ts — semantic categorization
```

**Lines:** 991 across 6 files

### 4.1 Delegation Enforcer (`src/features/delegation-enforcer.ts`)

**Lines:** 304
**What it does:** Middleware that ensures every Task/Agent call has the correct model
parameter. Runs on every PreToolUse event for delegation tools.

**`enforceModel(agentInput)` algorithm:**
1. Canonicalize subagent_type (strip `oh-my-claudecode:` prefix, normalize role name)
2. If `forceInherit` enabled → strip model parameter (agents inherit parent model)
3. If model already specified → normalize to CC alias (sonnet/opus/haiku)
4. Otherwise: look up agent definition → get default model → apply modelAliases from
   config → normalize to CC alias → inject
5. If resolved model is 'inherit' → strip model parameter

**`isAgentCall(toolName, toolInput)` detection:**
- Tool name must be 'agent' or 'task' (case-insensitive)
- Input must have `subagent_type: string`, `prompt: string`, `description: string`

**Config caching:**
- Builds cache key from 20+ environment variables
- Invalidates when any env var changes
- Skipped in VITEST environment (so mocks work)

**Model normalization:** Full model IDs like `claude-sonnet-4-6` are converted
to CC aliases (`sonnet`) to prevent 400 errors on Bedrock/Vertex.

### 4.2 Delegation Routing (`src/features/delegation-routing/`)

**Lines:** 291 across 3 files
**What it does:** Resolves which provider/tool to use for agent roles.

**`resolveDelegation(options)` precedence:**
1. Explicit tool invocation → always Claude Task
2. Configured routing (if enabled) → from config roles map
3. Default heuristic → ROLE_CATEGORY_DEFAULTS map → Claude subagent
4. defaultProvider fallback → Claude Task

**Deprecated providers:** codex and gemini log warnings and fall back to Claude Task.

**Fallback chain:** `["claude:explore", "codex:gpt-5"]` parsed into
`[{provider, agentOrModel}]` entries.

**Output:**
```typescript
interface DelegationDecision {
  provider: 'claude' | 'codex' | 'gemini';  // In practice always 'claude'
  tool: 'Task';                               // Always 'Task'
  agentOrModel: string;
  reason: string;
  fallbackChain?: string[];
}
```

### 4.3 Delegation Categories (`src/features/delegation-categories/index.ts`)

**Lines:** 333 + 63 (types) = 396
**What it does:** Semantic task categorization that determines tier, temperature,
and thinking budget.

**7 categories:**

| Category | Tier | Temperature | Thinking Budget | Tokens |
|----------|------|-------------|-----------------|--------|
| visual-engineering | HIGH | 0.7 | high | 10,000 |
| ultrabrain | HIGH | 0.3 | max | 32,000 |
| artistry | MEDIUM | 0.9 | medium | 5,000 |
| quick | LOW | 0.1 | low | 1,000 |
| writing | MEDIUM | 0.5 | medium | 5,000 |
| unspecified-low | LOW | 0.3 | low | 1,000 |
| unspecified-high | HIGH | 0.5 | high | 10,000 |

**Category detection algorithm:**
1. If explicit tier → use unspecified-low or unspecified-high
2. If explicit category → use it
3. Auto-detect from prompt keywords: score each category by keyword matches
4. Require >=2 keyword matches for confidence
5. Default: unspecified-high (MEDIUM tier)

**Keywords per category:** ~12-19 keywords each (e.g., visual-engineering: ui, ux,
design, frontend, component, style, css, visual, layout, ...)

**Category also provides `promptAppend`** — extra instructions appended to prompts
(e.g., "Focus on visual design, user experience, and aesthetic quality.")

---

## Key Patterns for Replication

### Pattern 1: Stop Hook Enforcement
The core pattern is: intercept Stop events → check priority-ordered modes → inject
continuation prompts or allow stop. The "soft enforcement" approach (message injection)
is preferred over hard blocking to prevent deadlocks.

### Pattern 2: Session-Isolated State
Every state file includes `session_id`. Reads validate ownership. Ghost-legacy
cleanup prevents state leakage between sessions. Session paths:
`.omc/state/sessions/{sessionId}/`.

### Pattern 3: Atomic State Persistence
All state writes use temp-file + fsync + rename. This prevents corruption from
crashes mid-write. The mode-state-io layer adds `_meta` envelopes with timestamps.

### Pattern 4: Circuit Breakers
Team and ralplan modes have circuit breakers (max reinforcement counts with TTL).
Todo continuation has max 5 attempts. Ralph has hard max iterations from security
config. These prevent infinite loops.

### Pattern 5: Transcript-Based Signal Detection
Autopilot detects phase completion by searching session transcripts for literal
signal strings. Ralph's verifier searches transcript tails (last 32KB) for
approval/rejection patterns. This is the bridge between prompt-level instructions
and code-level enforcement.

### Pattern 6: Weighted Multi-Signal Scoring
Model routing combines lexical analysis (keywords, word count), structural analysis
(subtasks, impact scope), and context (failures, chain depth) into a weighted score.
Rules engine provides agent-specific overrides. Divergence between scorer and rules
reduces confidence and prefers the higher tier.

### Pattern 7: Cancellation Protocol
Cancel involves: cancel signal file (30s TTL) → state deactivation → state file
deletion → linked mode cleanup. Multiple bypass points ensure cancel always works
(explicit command, signal file, context limit, rate limit, auth error).

---

## File Inventory

### Hooks (7,466 lines)
| File | Lines | Purpose |
|------|-------|---------|
| persistent-mode/index.ts | 1,310 | Core stop enforcement engine |
| bridge.ts | 2,421 | Shell hook router |
| ralph/loop.ts | 539 | Ralph state machine |
| ralph/progress.ts | 511 | Append-only progress log |
| ralph/prd.ts | 438 | PRD document tracking |
| ralph/verifier.ts | 333 | Architect verification |
| ralph/index.ts | 151 | Re-exports |
| autopilot/state.ts | 644 | Phase state machine |
| autopilot/enforcement.ts | 555 | Signal detection + enforcement |
| autopilot/pipeline.ts | 555 | Configurable pipeline |
| autopilot/types.ts | 279 | Type definitions |
| autopilot/index.ts | 158 | Re-exports |

### State Management (1,793 lines)
| File | Lines | Purpose |
|------|-------|---------|
| state-manager/index.ts | 818 | Unified state API with caching |
| state-manager/types.ts | 158 | Type definitions |
| mode-state-io.ts | 247 | Mode-specific state I/O |
| atomic-write.ts | 262 | Crash-safe file writes |
| boulder-state/storage.ts | 214 | Plan state with file locking |
| boulder-state/types.ts | 54 | Type definitions |
| boulder-state/index.ts | 42 | Re-exports |

### Model Routing (1,626 lines)
| File | Lines | Purpose |
|------|-------|---------|
| router.ts | 348 | Main routing engine |
| signals.ts | 323 | Signal extraction |
| scorer.ts | 287 | Weighted complexity scoring |
| rules.ts | 285 | Priority-ordered rules engine |
| types.ts | 265 | Types + constants + keyword lists |
| index.ts | 118 | Re-exports + convenience functions |

### Delegation (991 lines)
| File | Lines | Purpose |
|------|-------|---------|
| delegation-categories/index.ts | 333 | Semantic task categorization |
| delegation-enforcer.ts | 304 | Model parameter enforcement |
| delegation-routing/resolver.ts | 172 | Provider/tool resolution |
| delegation-routing/types.ts | 93 | Types + defaults |
| delegation-categories/types.ts | 63 | Category type definitions |
| delegation-routing/index.ts | 26 | Re-exports |
