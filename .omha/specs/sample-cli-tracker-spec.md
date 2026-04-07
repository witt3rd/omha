---
version: "1.0"
status: confirmed
created: "2026-04-07T06:45:00Z"
interview_id: "di-20260407-x7k"
project_name: "cli-tracker"
type: greenfield
coverage:
  goal: CLEAR
  constraints: LOW
  success_criteria: CLEAR
  existing_context: N/A
rounds_completed: 4
---

# cli-tracker — Requirements Specification

## Goal

Build a minimal CLI task tracker for personal use. The tool reads tasks from a
YAML file, displays today's items filtered by due date, and lets the user mark
tasks as complete. It's a personal productivity tool — no multi-user, no server,
no sync. The primary user is a developer who lives in the terminal and wants
something simpler than a full project management tool.

## Constraints

- **Technical**: Python 3.11+, single-file script or small package, no external services
- **Resources**: Solo developer, ship MVP in one session
- **Compatibility**: Linux and macOS, no Windows requirement
- **Timeline**: Working MVP today, polish later
- **Dependencies**: PyYAML for config, rich for terminal output — nothing else

## Success Criteria

1. `tracker list` shows all tasks, with today's tasks highlighted
2. `tracker add "task description" --due 2026-04-10` adds a task with a due date
3. `tracker done <id>` marks a task as complete
4. `tracker list --today` filters to tasks due today or overdue
5. Tasks persist in `~/.tracker/tasks.yaml` between invocations
6. Handles empty task list gracefully (shows helpful message, not error)
7. Rejects duplicate task IDs

## Existing Context

N/A — greenfield project.

## Assumptions

- User has Python 3.11+ installed
- YAML is an acceptable storage format (no database needed at this scale)
- Task IDs can be auto-generated (incrementing integers)
- "Today" means the local system date

## Open Questions

- Should completed tasks be archived or deleted? (Suggest: archived to a separate section in the YAML)
- Should there be a `tracker edit` command in MVP or defer to v2?
