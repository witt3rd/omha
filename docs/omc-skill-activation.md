# OMC Skill Activation & Context Injection System

Analysis of how Oh-My-ClaudeCode (OMC) automatically detects keywords, activates
skills, and injects them into agent context. This is the "zero learning curve"
mechanism — users just type naturally and skills activate.

---

## Architecture Overview

```
User Prompt
    │
    ▼
┌─────────────────────────────┐
│  keyword-detector.mjs       │  Claude Code hook (UserPromptSubmit)
│  (scripts/ — shell hook)    │  Runs as external Node.js process
│                             │  Reads stdin JSON, writes stdout JSON
└───────────┬─────────────────┘
            │ detects keywords via regex
            ▼
┌─────────────────────────────┐
│  SKILL.md files             │  skills/<name>/SKILL.md
│  (loaded directly from disk)│  Loaded inline via loadSkillContent()
└───────────┬─────────────────┘
            │ content injected into additionalContext
            ▼
┌─────────────────────────────┐
│  Claude Code Hook API       │  { continue: true, hookSpecificOutput: {
│                             │      hookEventName: 'UserPromptSubmit',
│                             │      additionalContext: <skill content>
│                             │  }}
└───────────┬─────────────────┘
            │
            ▼
     Agent sees skill instructions
     prepended to user's prompt

    (parallel path)
            │
┌───────────┴─────────────────┐
│  skill-injector.mjs         │  Separate hook for LEARNED skills
│  (scripts/ — shell hook)    │  Scans .omc/skills/ dirs for .md files
│                             │  Matches by YAML frontmatter triggers
└─────────────────────────────┘
```

There are TWO parallel injection systems:
1. **keyword-detector.mjs** — detects magic keywords → loads BUILTIN skills
2. **skill-injector.mjs** — matches learned skills from .omc/skills/ dirs

Plus an in-process TypeScript layer:
3. **magic-keywords.ts** — lightweight prompt enhancement (search/analyze/ultrathink)
4. **context-injector/** — priority-ordered context collection framework
5. **builtin-skills/** — skill loading from SKILL.md files
6. **skill-state/** — stop-hook protection for running skills

---

## 1. KEYWORD DETECTOR (Primary Activation Engine)

### Source Files
- `scripts/keyword-detector.mjs` — the actual Claude Code hook script
- `src/hooks/keyword-detector/index.ts` — TypeScript library (shared logic)

### How It Works

The keyword detector runs as an external Node.js script invoked by Claude Code's
`UserPromptSubmit` hook event. It:

1. **Reads stdin** — receives JSON with `{ prompt, session_id, cwd }`
2. **Sanitizes text** — strips code blocks, XML tags, URLs, file paths
3. **Tests regex patterns** against the cleaned prompt
4. **Filters informational queries** — "what is ralph?" does NOT activate ralph
5. **Resolves conflicts** — cancel beats everything; priority ordering applied
6. **Loads skill content** — reads SKILL.md files directly from disk
7. **Outputs hook response** — JSON with `additionalContext` field

### Keyword → Skill Mapping

Keywords are hardcoded regex patterns that map to skill names:

```
KEYWORD REGEX                                    SKILL NAME
──────────────────────────────────────           ──────────
/\b(cancelomc|stopomc)\b/i                       cancel
/\b(ralph|don't stop|must complete)\b/i          ralph
/\b(autopilot|auto pilot|fullsend)\b/i           autopilot
/\b(ultrawork|ulw|uw)\b/i                        ultrawork
/\b(ccg|claude-codex-gemini)\b/i                 ccg
/\b(ralplan)\b/i                                 ralplan
/\b(deep[\s-]interview|ouroboros)\b/i            deep-interview
/\b(tdd)\b|\btest\s+first\b/i                   tdd
/\b(code\s+review|review\s+code)\b/i            code-review
/\b(security\s+review)\b/i                      security-review
/\b(ultrathink|think hard)\b/i                  ultrathink
/\b(deepsearch)\b|search\s+the\s+codebase/i     deepsearch
/\b(deep[\s-]?analyze)\b/i                      analyze
/\b(wiki)\b/i                                   wiki
```

Additional "intent detection" for autopilot:
```
/\b(build|create|make)\s+me\s+.*(app|feature|project|tool)\b/i
/\bi\s+want\s+a\s+/i
/\bhandle\s+it\s+all\b/i
/\bend\s+to\s+end\b/i
```

### Korean Language Support

All major keywords have Korean regex alternatives:
- ralph: 랄프
- autopilot: 오토파일럿
- ultrawork: 울트라워크
- ralplan: 랄플랜
- tdd: 테스트 퍼스트
- etc.

### Priority Order (Conflict Resolution)

```
1. cancel          (exclusive — suppresses everything)
2. ralph
3. autopilot
4. ultrawork
5. ccg
6. ralplan
7. deep-interview
8. ai-slop-cleaner
9. tdd
10. code-review
11. security-review
12. ultrathink
13. deepsearch
14. analyze
```

### Informational Intent Filter

Keywords are NOT activated when surrounded by informational context:
```
"what is ralph?" → NOT activated (informational pattern detected)
"ralph fix all the tests" → ACTIVATED (actionable)
```

Detection uses a ±80 character window around the keyword match, checking for
patterns like "what is", "how to use", "explain", "tell me about" (in EN/KR/JP/ZH).

### Anti-Slop Detector (Compound Pattern)

The ai-slop-cleaner skill uses a special compound detection:
- EXPLICIT: "ai slop", "anti-slop", "deslop"
- OR: ACTION word + SMELL word
  - ACTION: "cleanup", "refactor", "simplify", "dedupe", "prune"
  - SMELL: "slop", "duplicate", "dead code", "over-abstraction", "wrapper layers"

### Task Size Gate

Heavy orchestration modes (ralph, autopilot, team, ultrawork) are suppressed
for small tasks (< 50 words) to avoid over-orchestration:

```typescript
getAllKeywordsWithSizeCheck(text, {
  smallWordLimit: 50,    // below = small task
  largeWordLimit: 200,   // above = large task
  suppressHeavyModesForSmallTasks: true
})
```

### Ralplan Gate (Underspecification Guard)

Vague prompts with execution keywords get redirected to ralplan (planning):
```
"ralph do the thing" → redirected to ralplan (underspecified)
"ralph fix src/auth/login.ts validation bug" → passes through (well-specified)
```

Well-specified signals that bypass the gate:
- File paths with extensions (*.ts, *.py, etc.)
- CamelCase/snake_case identifiers
- Issue/PR numbers (#123)
- Numbered steps or bullet lists
- Error references or stack traces
- Code blocks with substantial content

Escape hatches: prefix with `force:` or `!` to bypass.

---

## 2. SKILL LOADING & INJECTION

### How Skills Are Loaded Into Context

When keyword-detector.mjs finds a match, it calls `loadSkillContent(skillName)`:

```javascript
function loadSkillContent(skillName) {
  const skillPath = join(_omcRoot, 'skills', skillName, 'SKILL.md');
  return readFileSync(skillPath, 'utf8');  // raw markdown content
}
```

The skill content is wrapped in an invocation message:

```
[MAGIC KEYWORD: RALPH]

<full content of skills/ralph/SKILL.md>

---
User request:
<original user prompt>
```

For multiple keywords detected simultaneously:
```
[MAGIC KEYWORDS DETECTED: RALPH, TDD]

### Skill 1: RALPH
<ralph SKILL.md content>

### Skill 2: TDD
<tdd SKILL.md content>

User request:
<original prompt>

IMPORTANT: Complete ALL skills listed above in order.
```

### Fallback: Skill Tool Invocation

If the SKILL.md file isn't found on disk (shouldn't happen for builtin skills),
it falls back to requesting a tool invocation:

```
[MAGIC KEYWORD: RALPH]
You MUST invoke the skill using the Skill tool:
Skill: oh-my-claudecode:ralph
IMPORTANT: Invoke the skill IMMEDIATELY.
```

### Simple Mode Messages (No Skill File)

Some keywords inject short inline messages instead of loading SKILL.md files:

| Keyword          | Injection                              |
|------------------|----------------------------------------|
| ultrathink       | `<think-mode>` extended reasoning instructions |
| deepsearch       | `<search-mode>` parallel search instructions   |
| analyze          | `<analyze-mode>` context-gathering instructions |
| tdd              | `<tdd-mode>` test-first instructions            |
| code-review      | `<code-review-mode>` review instructions        |
| security-review  | `<security-review-mode>` review instructions    |

These are handled BEFORE skill invocation — the keyword is removed from the
`resolved` list and its message is prepended to the output.

---

## 3. SKILL INJECTOR (Learned Skills)

### Source File
- `scripts/skill-injector.mjs`

### Purpose

Separate from the keyword detector, this hook injects LEARNED skills — skills
that were extracted from previous sessions and saved as .md files.

### Skill Discovery Locations (Priority Order)

1. **Project-level**: `.omc/skills/*.md` (in current working directory)
2. **Global**: `~/.omc/skills/*.md`
3. **Legacy user**: `~/.claude/skills/omc-learned/*.md`

### Matching Mechanism

Each skill file has YAML frontmatter with triggers:
```yaml
---
name: My Custom Skill
triggers:
  - "deploy"
  - "kubernetes"
  - "k8s"
---
Skill content here...
```

The injector does simple substring matching:
```javascript
for (const trigger of skill.triggers) {
  if (promptLower.includes(trigger)) {
    score += 10;
  }
}
```

### Injection Format

Matched skills are wrapped in `<mnemosyne>` tags:
```xml
<mnemosyne>

## Relevant Learned Skills

The following skills from previous sessions may help:

### My Custom Skill (project)
<skill-metadata>{"path":"...","triggers":[...],"score":10,"scope":"project"}</skill-metadata>

Skill content here...

---

</mnemosyne>
```

### Limits & Deduplication

- Max 5 skills per session (`MAX_SKILLS_PER_SESSION = 5`)
- Skills already injected in a session are not re-injected (tracked by path)
- In-memory cache per session (resets each process invocation in fallback mode)
- Bridge mode provides persistent session cache across invocations

---

## 4. MAGIC KEYWORDS (In-Process Enhancement)

### Source File
- `src/features/magic-keywords.ts`

### Purpose

A lighter-weight, in-process keyword system that enhances prompts with
behavioral modifiers. Unlike the hook-based keyword-detector, this runs
inside the TypeScript process.

### Four Built-in Enhancements

| Enhancement   | Triggers                              | Action                         |
|---------------|---------------------------------------|--------------------------------|
| ultrawork     | ultrawork, ulw, uw                    | Injects full ultrawork mode prompt with agent utilization rules |
| search        | search, find, locate, explore, etc.   | Appends `[search-mode]` parallel search instructions |
| analyze       | analyze, investigate, debug, etc.     | Appends `[analyze-mode]` context-gathering instructions |
| ultrathink    | ultrathink, think, reason, ponder     | Wraps in `[ULTRATHINK MODE]` deep reasoning instructions |

### Progressive Disclosure

The magic keywords system uses a "detect and enhance" pattern:
- Triggers are broad (many natural language words)
- Enhancement is appended/prepended to the original prompt
- Original prompt is preserved (not replaced)
- Trigger words are stripped only for ultrawork/ultrathink

### Configurable Triggers

Triggers can be overridden via plugin config:
```typescript
const processor = createMagicKeywordProcessor({
  ultrawork: ['ultrawork', 'ulw', 'my-custom-trigger'],
  search: ['search', 'find'],
  analyze: ['analyze'],
  ultrathink: ['ultrathink']
});
```

### Ultrawork Agent-Aware Injection

Ultrawork mode detects if the agent is a "planner" type and provides
different instructions:
- **Planner agents**: Get context-gathering focused instructions, told NOT to implement
- **Other agents**: Get full agent utilization + verification guarantee instructions

---

## 5. BUILTIN SKILLS (SKILL.md Loading)

### Source Files
- `src/features/builtin-skills/skills.ts` — loads from disk
- `src/features/builtin-skills/runtime-guidance.ts` — appends runtime info

### Skill Loading Pipeline

```
skills/<name>/SKILL.md
    │
    ▼ readFileSync()
    │
    ▼ parseFrontmatter() → { metadata, body }
    │
    ▼ rewriteOmcCliInvocations() — rewrites CLI references
    │
    ▼ renderSkillRuntimeGuidance() — appends runtime availability info
    │
    ▼ renderSkillPipelineGuidance() — appends pipeline handoff info
    │
    ▼ renderSkillResourcesGuidance() — appends resource paths
    │
    ▼ BuiltinSkill object with { name, aliases, description, template }
```

### SKILL.md Frontmatter Format

```yaml
---
name: ralph
description: Persistence until verified complete
aliases:
  - dont-stop
agent: executor
model: sonnet
argument-hint: "task description"
pipeline: [ralplan, ralph]
next-skill: verify
next-skill-args: --strict
handoff: .omc/plans/plan.md
---

# Skill body (markdown)
```

### Runtime Guidance Injection

For specific skills (ralph, ralplan/plan, deep-interview), runtime availability
is detected and appended:

```typescript
// Checks if codex/gemini CLIs are installed
detectSkillRuntimeAvailability() → { claude: true, codex: true, gemini: false }
```

If Codex CLI is available, skills get additional guidance:
- **ralplan**: "Use `omc ask codex --agent-prompt <role>` for architect/critic passes"
- **ralph**: "Use `omc ask codex --agent-prompt critic` for approval pass"
- **deep-interview**: Lists Codex variant commands for post-interview execution

### Name Collision Avoidance

Skills that collide with Claude Code native commands get prefixed:
```
review → omc-review
plan → omc-plan
security-review → omc-security-review
init → omc-init
```

### Skill Count

~30 builtin skills organized in `skills/` directory, each as `<name>/SKILL.md`.

---

## 6. CONTEXT INJECTOR (Framework)

### Source Files
- `src/features/context-injector/collector.ts`
- `src/features/context-injector/injector.ts`
- `src/features/context-injector/types.ts`

### Purpose

A generic, priority-ordered context collection and injection framework.
Multiple sources can register context entries that get merged and injected
into prompts.

### Context Sources

```typescript
type ContextSourceType =
  | 'keyword-detector'    // Magic keyword detections
  | 'rules-injector'      // Rule files (.claude/rules/)
  | 'directory-agents'    // AGENTS.md files
  | 'directory-readme'    // README.md files
  | 'boulder-state'       // Plan state
  | 'session-context'     // Session-level context
  | 'learner'             // Learned skills
  | 'beads'               // Bead context
  | 'project-memory'      // Project memory
  | 'custom'              // Custom context
```

### Priority System

```
critical (0) → high (1) → normal (2) → low (3)
```

Entries are sorted by priority, then by timestamp (earlier first).

### Collection → Injection Flow

```
1. Sources register context:
   collector.register(sessionId, {
     id: 'keyword-ralph',
     source: 'keyword-detector',
     content: '<ralph skill content>',
     priority: 'high'
   });

2. On next message, context is consumed:
   const pending = collector.consume(sessionId);
   // Returns merged content, clears entries

3. Injected into prompt:
   injectPendingContext(collector, sessionId, messageParts, 'prepend')
   // Prepends merged context before the user's message
```

### Injection Strategies

| Strategy | Result                                              |
|----------|-----------------------------------------------------|
| prepend  | `<context>\n---\n<original>`                        |
| append   | `<original>\n---\n<context>`                        |
| wrap     | `<injected-context>\n<context>\n</injected-context>\n---\n<original>` |

### Deduplication

Entries are keyed by `source:id`. Re-registering with the same key replaces
the previous entry (not duplicated).

---

## 7. SKILL STATE (Stop-Hook Protection)

### Source File
- `src/hooks/skill-state/index.ts`

### Purpose

Prevents Claude Code from prematurely terminating while a skill is executing.
The persistent-mode Stop hook checks skill state and blocks termination.

### Protection Levels

```
LEVEL    MAX_REINFORCEMENTS   STALE_TTL
──────   ──────────────────   ─────────
none     0                    0          (instant/has own state)
light    3                    5 min      (simple shortcuts)
medium   5                    15 min     (review/planning)
heavy    10                   30 min     (long-running)
```

### Skill → Protection Mapping

```
NONE (already have mode state or instant):
  autopilot, ralph, ultrawork, team, ultraqa, cancel
  trace, hud, omc-doctor, omc-help, note

LIGHT (simple shortcuts):
  skill, ask, configure-notifications

MEDIUM (review/planning):
  omc-plan, plan, review, external-context, ai-slop-cleaner,
  sciomc, learner, omc-setup, mcp-setup, psm, writer-memory,
  ralph-init, release, ccg

HEAVY (long-running):
  deepinit, deep-interview, self-improve
```

### State File

Written to: `.omc/state/sessions/<sessionId>/skill-active-state.json`

```json
{
  "active": true,
  "skill_name": "deep-interview",
  "session_id": "abc123",
  "started_at": "2025-01-01T00:00:00Z",
  "last_checked_at": "2025-01-01T00:05:00Z",
  "reinforcement_count": 2,
  "max_reinforcements": 10,
  "stale_ttl_ms": 1800000
}
```

### Stop Hook Enforcement Flow

```
Stop event fires
    │
    ▼ readSkillActiveState()
    │
    ├── no state or inactive → allow stop
    ├── wrong session_id → allow stop
    ├── stale (exceeded TTL) → clear state, allow stop
    ├── exceeded max_reinforcements → clear state, allow stop
    ├── active subagents running → allow idle (don't consume reinforcement)
    │
    └── BLOCK: increment reinforcement_count, inject message:
        "[SKILL ACTIVE: deep-interview] Still executing
         (reinforcement 3/10). Continue working."
```

### Nesting Guard

When a skill invokes a child skill (e.g., omc-setup calls mcp-setup), the
child does NOT overwrite the parent's active state. Only the same skill can
refresh its own state (idempotent).

### OMC-Prefix Guard

Only skills invoked with the `oh-my-claudecode:` prefix get protection.
Project custom skills (e.g., user's `.claude/skills/plan/`) are not confused
with OMC builtins of the same name.

---

## 8. MODE STATE MANAGEMENT

### State Files (Execution Modes)

For heavy orchestration modes (ralph, autopilot, ultrawork, ralplan), the
keyword detector creates JSON state files:

```
.omc/state/sessions/<sessionId>/ralph-state.json
.omc/state/sessions/<sessionId>/autopilot-state.json
.omc/state/sessions/<sessionId>/ultrawork-state.json
.omc/state/sessions/<sessionId>/ralplan-state.json
```

Fallback (no session ID): `.omc/state/<name>-state.json`

### Ralph State (Special Fields)

```json
{
  "active": true,
  "iteration": 1,
  "max_iterations": 100,
  "started_at": "...",
  "prompt": "<original prompt>",
  "session_id": "...",
  "project_path": "/path/to/project",
  "linked_ultrawork": true,
  "awaiting_confirmation": true,
  "last_checked_at": "..."
}
```

### Cancel Mechanism

The `cancel` keyword clears ALL mode state files:
```javascript
clearStateFiles(directory, ['ralph', 'autopilot', 'ultrawork', 'swarm', 'ralplan'], sessionId);
```

### Cross-Mode Composition

Ralph automatically activates ultrawork state (`linked_ultrawork: true`).
Ralph + team can be linked (`linked_team: true` / `linked_ralph: true`).

---

## 9. COMPLETE ACTIVATION FLOW (End-to-End)

### Example: User types "ralph fix the auth bug in src/auth/login.ts"

```
1. Claude Code fires UserPromptSubmit hook
2. keyword-detector.mjs receives: { prompt: "ralph fix the auth..." }
3. Sanitization: strips code blocks, XML, URLs, paths
4. Regex match: /\b(ralph)\b/i matches "ralph"
5. Informational check: no "what is" nearby → actionable
6. Conflict resolution: only ralph → [{ name: 'ralph' }]
7. Ralplan gate: has file path "src/auth/login.ts" → well-specified → passes
8. State activation: writes ralph-state.json + ultrawork-state.json
9. Skill loading: reads skills/ralph/SKILL.md from disk
10. Output: { continue: true, hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: "[MAGIC KEYWORD: RALPH]\n\n<ralph SKILL.md>\n\n---\nUser request:\nralph fix the auth bug..."
    }}
11. Claude Code prepends additionalContext to the conversation
12. Agent sees ralph skill instructions + original prompt
13. skill-state writes skill-active-state.json (if protection != none)
14. Stop hook now blocks premature termination
```

### Example: User types "search the codebase for unused imports"

```
1. keyword-detector.mjs matches: deepsearch
2. deepsearch is a MODE_MESSAGE_KEYWORD (no SKILL.md)
3. Outputs inline message: "<search-mode>MAXIMIZE SEARCH EFFORT..."
4. Agent receives search mode instructions
```

---

## 10. KEY DESIGN PATTERNS FOR HERMES

### What to Adopt

1. **Regex keyword detection with sanitization** — strip code blocks, XML, URLs
   before matching to avoid false positives

2. **Informational intent filtering** — don't activate skills when the user is
   asking ABOUT the keyword, not invoking it

3. **Priority-based conflict resolution** — when multiple keywords match,
   use a fixed priority order

4. **Task-size gating** — suppress heavy orchestration for small tasks

5. **Underspecification guard** — redirect vague prompts to planning first

6. **additionalContext injection** — Claude Code's hook API allows prepending
   context to the user's prompt via hookSpecificOutput.additionalContext

7. **Progressive disclosure** — simple keywords inject short mode messages,
   complex workflows inject full SKILL.md content

8. **Skill state tracking** — prevent premature termination with reinforcement
   counting and TTL-based staleness

### Key Differences from Hermes

| Aspect              | OMC                                    | Hermes                    |
|---------------------|----------------------------------------|---------------------------|
| Detection method    | Regex patterns on user prompt          | Description-based matching |
| Skill format        | SKILL.md with YAML frontmatter         | Skill objects in code      |
| Injection mechanism | Claude Code hook additionalContext      | System prompt construction |
| State management    | JSON files in .omc/state/              | In-memory                  |
| Learned skills      | Separate skill-injector hook           | Not yet implemented        |
| Multi-language      | EN + KR + JP + ZH keywords             | EN only                    |
| Pipeline support    | YAML frontmatter pipeline/next-skill   | Not yet implemented        |
