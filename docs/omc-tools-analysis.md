# OMC Tools Layer Analysis

Analysis of the MCP tools and custom tools that OMC skills invoke.
Source: `/home/dt/src/ext/oh-my-claudecode/`

## Architecture Overview

OMC exposes tools via an in-process MCP server named `"t"`. All tools are
accessible as `mcp__t__<tool_name>` to skills and subagents. There are two
server implementations:

1. **In-process SDK server** (`src/mcp/omc-tools-server.ts`): Uses
   `createSdkMcpServer` from `@anthropic-ai/claude-agent-sdk`. This is the
   primary path for subagent tool access.

2. **Standalone stdio server** (`src/mcp/standalone-server.ts`): Uses the
   official `@modelcontextprotocol/sdk` Server over StdioServerTransport.
   Registered in `.mcp.json` for Claude Code's MCP discovery.

Both aggregate the same tool arrays. Tools are organized by **category** with
an env-var disable mechanism (`OMC_DISABLE_TOOLS=lsp,python-repl,...`).

### Tool Categories

| Category       | Tool Count | Disable Key       |
|----------------|-----------|-------------------|
| LSP            | 12        | `lsp`             |
| AST            | 2         | `ast`             |
| Python REPL    | 1         | `python`          |
| Skills         | 3         | `skills`          |
| State          | 5         | `state`           |
| Notepad        | 6         | `notepad`         |
| Memory         | 4         | `memory`          |
| Trace          | 3         | `trace`           |
| Shared Memory  | ?         | `shared-memory`   |
| Interop        | ?         | `interop`         |
| DeepInit       | 1         | `deepinit`        |
| Wiki           | ?         | `wiki`            |

### Tool Definition Pattern

Every tool follows this shape:

```typescript
interface ToolDef {
  name: string;
  description: string;
  schema: z.ZodRawShape;  // Zod schema for params
  handler: (args: unknown) => Promise<{
    content: Array<{ type: 'text'; text: string }>;
    isError?: boolean;
  }>;
}
```

Skills invoke tools by name via MCP: `mcp__t__<tool_name>`.

---

## 1. STATE TOOLS (Category: state)

File: `src/tools/state-tools.ts`

Manages execution mode state as JSON files in `.omc/state/`. Supports
session-scoped isolation via `session_id` parameter. Modes supported:
`autopilot`, `team`, `ralph`, `ultrawork`, `ultraqa`, `ralplan`,
`omc-teams`, `deep-interview`, `self-improve`, `skill-active`.

### state_read

```
Params:
  mode: enum[autopilot|team|ralph|ultrawork|ultraqa|ralplan|omc-teams|deep-interview|self-improve|skill-active]
  workingDirectory?: string
  session_id?: string
```

**Mechanics**: Reads JSON state file for a given mode. With `session_id`,
reads from session-scoped path only. Without it, aggregates legacy state
plus all session-scoped state files.

**State**: Reads `.omc/state/<mode>-state.json` or
`.omc/state/sessions/<session_id>/<mode>-state.json`.

**Annotations**: `readOnlyHint: true, idempotentHint: true`

### state_write

```
Params:
  mode: enum[...]
  active?: boolean
  iteration?: number
  max_iterations?: number
  current_phase?: string (max 200)
  task_description?: string (max 2000)
  plan_path?: string (max 500)
  started_at?: string (max 100)
  completed_at?: string (max 100)
  error?: string (max 2000)
  state?: Record<string, unknown>  // custom fields merged in
  workingDirectory?: string
  session_id?: string
```

**Mechanics**: Builds state object from explicit params + custom `state` bag.
Explicit params take precedence. Adds `_meta` with mode, sessionId,
updatedAt, updatedBy. Uses `atomicWriteJsonSync` for crash safety.
Validates payload size limits.

**State**: Writes to `.omc/state/` (legacy) or session-scoped path.

### state_clear

```
Params:
  mode: enum[...]
  workingDirectory?: string
  session_id?: string
```

**Mechanics**: Deletes state file(s). With `session_id`, writes a cancel
signal (TTL 30s) then clears session-specific + legacy state. For `team`
mode, also cleans up team runtime state dirs and prunes HUD mission
board entries.

**Annotations**: `destructiveHint: true`

### state_list_active

```
Params:
  workingDirectory?: string
  session_id?: string
```

**Mechanics**: Iterates all modes, checks which have `active: true` in
their state files. With session_id, checks only that session. Without it,
scans all sessions + legacy paths.

### state_get_status

```
Params:
  mode?: enum[...]  // optional — omit for all modes
  workingDirectory?: string
  session_id?: string
```

**Mechanics**: Returns detailed status including active flag, file paths,
state preview (truncated to 500 chars), and active sessions per mode.

---

## 2. MEMORY TOOLS (Category: memory)

File: `src/tools/memory-tools.ts`

Manages project-scoped persistent memory stored as JSON in `.omc/`.
Memory has structured sections: techStack, build, conventions, structure,
customNotes, userDirectives.

### project_memory_read

```
Params:
  section?: enum[all|techStack|build|conventions|structure|notes|directives]
  workingDirectory?: string
```

**Mechanics**: Loads project memory via `loadProjectMemory(root)`. Returns
the full memory or a specific section. Memory is auto-detected during first
session run.

**State**: Reads `.omc/project-memory.json` (via `getWorktreeProjectMemoryPath`).

### project_memory_write

```
Params:
  memory: Record<string, unknown>  // the memory object
  merge?: boolean  // default false = replace
  workingDirectory?: string
```

**Mechanics**: Replaces or merges project memory. Merge uses
`mergeProjectMemory()`. Ensures required fields (version, lastScanned,
projectRoot).

**State**: Writes `.omc/project-memory.json`.

### project_memory_add_note

```
Params:
  category: string (max 50)
  content: string (max 1000)
  workingDirectory?: string
```

**Mechanics**: Appends a categorized note to memory's `customNotes` array.
Requires memory to already exist.

### project_memory_add_directive

```
Params:
  directive: string (max 500)
  context?: string (max 500)
  priority?: enum[high|normal]
  workingDirectory?: string
```

**Mechanics**: Adds a `UserDirective` with timestamp, source='explicit'.
Directives survive compaction and persist across sessions.

---

## 3. NOTEPAD TOOLS (Category: notepad)

File: `src/tools/notepad-tools.ts`

A three-section scratchpad stored in `.omc/`. Sections:
- **Priority Context**: Always loaded at session start. Short (~500 chars).
- **Working Memory**: Timestamped entries, auto-pruned after 7 days.
- **MANUAL**: Never auto-pruned; permanent notes.

### notepad_read

```
Params:
  section?: enum[all|priority|working|manual]
  workingDirectory?: string
```

**Mechanics**: Reads from the notepad file. Delegates to
`formatFullNotepad()`, `getPriorityContext()`, `getWorkingMemory()`, or
`getManualSection()`.

**State**: Reads `.omc/notepad.md` (via `getWorktreeNotepadPath`).

### notepad_write_priority

```
Params:
  content: string (max 2000)
  workingDirectory?: string
```

**Mechanics**: REPLACES the Priority Context section entirely. Warns if
over recommended 500 chars.

### notepad_write_working

```
Params:
  content: string (max 4000)
  workingDirectory?: string
```

**Mechanics**: APPENDS a timestamped entry to Working Memory section.

### notepad_write_manual

```
Params:
  content: string (max 4000)
  workingDirectory?: string
```

**Mechanics**: APPENDS an entry to the MANUAL section. Never auto-pruned.

### notepad_prune

```
Params:
  daysOld?: number (1-365, default 7)
  workingDirectory?: string
```

**Mechanics**: Removes Working Memory entries older than N days.

### notepad_stats

```
Params:
  workingDirectory?: string
```

**Mechanics**: Returns stats: total size, priority size, working memory
entry count, oldest entry.

---

## 4. TRACE TOOLS (Category: trace)

File: `src/tools/trace-tools.ts`

Reads session replay JSONL files from `.omc/state/agent-replay-<sessionId>.jsonl`.
Events include: agent_start/stop, tool_start/end, file_touch, intervention,
error, hook_fire/result, keyword_detected, skill_activated/invoked, mode_change.

### trace_timeline

```
Params:
  sessionId?: string  // auto-detects latest if omitted
  filter?: enum[all|hooks|skills|agents|keywords|tools|modes]
  last?: number       // limit to last N events
  workingDirectory?: string
```

**Mechanics**: Reads replay JSONL, filters by event category, formats as
chronological timeline with relative timestamps.

**State**: Reads `.omc/state/agent-replay-*.jsonl` (read-only).

### trace_summary

```
Params:
  sessionId?: string
  workingDirectory?: string
```

**Mechanics**: Aggregates stats from replay events: duration, agent counts,
hook stats, keyword frequencies, skill activations, mode transitions,
tool performance table (calls/avg/max/total ms), bottlenecks (>1s avg),
files touched. Also builds a narrative "Execution Flow".

### session_search (also in trace category)

Imported from `session-history-tools.ts`. Listed in `traceTools` array.

---

## 5. LSP TOOLS (Category: lsp)

File: `src/tools/lsp-tools.ts`
LSP Client: `src/tools/lsp/client.ts` (singleton `lspClientManager`)

All LSP tools use `withLspClient()` helper that:
1. Checks if a server config exists for the file type
2. Uses `lspClientManager.runWithClientLease()` to protect from idle eviction
3. Returns formatted results or install hints on error

### lsp_hover

```
Params: file: string, line: number (1-indexed), character: number (0-indexed)
```
Returns type info/docs at position. Delegates to `client.hover()`.

### lsp_goto_definition

```
Params: file: string, line: number, character: number
```
Finds definition location. Delegates to `client.definition()`.

### lsp_find_references

```
Params: file: string, line: number, character: number, includeDeclaration?: boolean
```
Finds all references across codebase. Delegates to `client.references()`.

### lsp_document_symbols

```
Params: file: string
```
Returns hierarchical symbol outline of a file.

### lsp_workspace_symbols

```
Params: query: string, file: string (for server selection)
```
Searches symbols across entire workspace.

### lsp_diagnostics

```
Params: file: string, severity?: enum[error|warning|info|hint]
```
Gets errors/warnings for a single file. Uses pull diagnostics if supported,
otherwise waits for push diagnostics (30s timeout).

### lsp_diagnostics_directory

```
Params: directory: string, strategy?: enum[tsc|lsp|auto]
```
Project-level diagnostics. `tsc` strategy runs `tsc --noEmit`. `lsp`
iterates files. `auto` prefers tsc when tsconfig.json exists.

### lsp_servers

```
Params: (none)
```
Lists all known language servers and installation status.

### lsp_prepare_rename

```
Params: file: string, line: number, character: number
```
Checks if rename is valid at position.

### lsp_rename

```
Params: file: string, line: number, character: number, newName: string
```
Previews rename edits (does NOT apply). Returns affected files/edits.

### lsp_code_actions

```
Params: file: string, startLine: number, startCharacter: number, endLine: number, endCharacter: number
```
Gets available refactorings/quick fixes for a selection.

### lsp_code_action_resolve

```
Params: file: string, startLine: number, startCharacter: number, endLine: number, endCharacter: number, actionIndex: number
```
Gets full edit details for a specific code action (by index from lsp_code_actions).

**State**: LSP tools are stateless from the tool perspective. The
`lspClientManager` singleton manages LSP server connections internally
(pooled by workspace+server key). Connections are auto-started and
idle-evicted.

---

## 6. AST TOOLS (Category: ast)

File: `src/tools/ast-tools.ts`

Uses `@ast-grep/napi` for structural code search/replace. Supports 17
languages. Gracefully degrades if ast-grep not installed.

### ast_grep_search

```
Params:
  pattern: string       // AST pattern with meta-vars ($NAME, $$$ARGS)
  language: enum[javascript|typescript|tsx|python|ruby|go|rust|java|kotlin|swift|c|cpp|csharp|html|css|json|yaml]
  path?: string         // dir or file (default: ".")
  context?: number      // lines of context (0-10, default: 2)
  maxResults?: number   // 1-100, default: 20
```

**Mechanics**: Walks directory for matching file extensions, parses each with
ast-grep, finds all pattern matches, formats with line numbers and context.
Skips `node_modules`, `.git`, `dist`, `build`, `__pycache__`, `.venv`.
Path validated against project root when `OMC_RESTRICT_TOOL_PATHS=true`.

**State**: Read-only. No state written.

### ast_grep_replace

```
Params:
  pattern: string       // pattern to match
  replacement: string   // replacement with same meta-vars
  language: enum[...]
  path?: string
  dryRun?: boolean      // default: true (preview only)
```

**Mechanics**: Finds matches like search, then applies replacements
preserving meta-variable captures. `dryRun=true` (default) only previews.
`dryRun=false` writes files.

**State**: Writes source files when `dryRun=false`.

---

## 7. SKILL TOOLS (Category: skills)

File: `src/tools/skills-tools.ts`

Discovers and loads learned skill markdown files from local and global dirs.

### load_omc_skills_local

```
Params:
  projectRoot?: string (max 500)
```

**Mechanics**: Calls `loadAllSkills(projectRoot)`, filters to `scope === 'project'`.
Returns skill metadata: id, name, description, triggers, tags, scope, path.
Validates projectRoot is under cwd or HOME (prevents path traversal).

**State**: Reads `.omc/skills/*.md` files. Read-only.

### load_omc_skills_global

```
Params: (none)
```

**Mechanics**: Calls `loadAllSkills(null)`, filters to `scope === 'user'`.
Loads from `~/.omc/skills/` and `$CLAUDE_CONFIG_DIR/skills/omc-learned/`.

### list_omc_skills

```
Params:
  projectRoot?: string (max 500)
```

**Mechanics**: Returns all skills (both project + user). Project skills
take priority over user skills with same ID.

---

## 8. PYTHON REPL (Category: python)

File: `src/tools/python-repl/tool.ts`

### python_repl

Not analyzed in detail here, but: executes Python code for data analysis.
Single tool with code input. Managed via bridge sessions.

---

## Summary: Tool Inventory for Hermes Replication

### High Priority (Core skill primitives)

| Tool | Category | Why |
|------|----------|-----|
| `state_read` | state | Skills read/write mode state constantly |
| `state_write` | state | Core loop control for execution modes |
| `state_clear` | state | Mode lifecycle management |
| `state_list_active` | state | Mode awareness |
| `notepad_read` | notepad | Cross-session memory |
| `notepad_write_priority` | notepad | Session bootstrap context |
| `notepad_write_working` | notepad | Working scratchpad |
| `project_memory_read` | memory | Project context |
| `project_memory_write` | memory | Project context persistence |
| `project_memory_add_note` | memory | Incremental learning |
| `project_memory_add_directive` | memory | User instruction persistence |

### Medium Priority (Useful for quality)

| Tool | Category | Why |
|------|----------|-----|
| `trace_timeline` | trace | Debugging/observability |
| `trace_summary` | trace | Session analysis |
| `list_omc_skills` | skills | Skill discovery |
| `load_omc_skills_local` | skills | Skill loading |
| `notepad_write_manual` | notepad | Permanent notes |
| `notepad_prune` | notepad | Maintenance |
| `state_get_status` | state | Detailed mode inspection |

### Lower Priority (IDE integration, may use Claude Code native)

| Tool | Category | Why |
|------|----------|-----|
| `lsp_*` (12 tools) | lsp | Claude Code already has LSP |
| `ast_grep_search` | ast | Structural search |
| `ast_grep_replace` | ast | Structural replace |
| `python_repl` | python | Data analysis |

### Key State Paths

All state lives under `.omc/` in the project root:
- `.omc/state/<mode>-state.json` — mode state (legacy)
- `.omc/state/sessions/<session_id>/<mode>-state.json` — session-scoped
- `.omc/project-memory.json` — project memory
- `.omc/notepad.md` — notepad (markdown format)
- `.omc/state/agent-replay-<sessionId>.jsonl` — trace data
- `.omc/skills/*.md` — project-local skills
- `~/.omc/skills/*.md` — global user skills

### Common Patterns

1. **All tools accept `workingDirectory?: string`** — defaults to `cwd()`.
   Used to resolve `.omc/` root.

2. **Session isolation via `session_id`** — State and clear tools support
   per-session scoping. Without it, operations are global/legacy.

3. **Return format is always** `{ content: [{ type: 'text', text: string }], isError?: boolean }`.

4. **Atomic writes** — State tools use `atomicWriteJsonSync` for crash safety.

5. **Payload validation** — `validatePayload()` enforces size limits on
   custom state data.

6. **Security** — AST/skill tools validate paths against project root
   boundary. Skill content is sanitized (role boundary tags stripped).
