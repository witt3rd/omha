# `.omh/` — OMH project metadata

This directory holds OMH workflow state and artifacts for the project rooted
at the parent directory. The convention is **selective sharing**, like
`.github/`: some subdirs are tracked in git (durable decision artifacts),
others are gitignored (ephemeral per-session runtime).

## Layout

| Subdir          | Tracked? | Lifetime          | Contents                                                         |
|-----------------|----------|-------------------|------------------------------------------------------------------|
| `state/`        | NO       | per-session       | Active mode state JSON (interview, ralplan, ralph, autopilot).   |
|                 |          |                   | Atomically written by `omh_state`. Cleared on success.           |
| `logs/`         | NO       | per-session       | Append-only event logs — decisions and transitions, not content. |
| `progress/`     | NO       | per-session       | Ralph execution progress logs.                                   |
| `specs/`        | YES      | durable           | Confirmed interview specs. Decision inputs.                      |
| `plans/`        | YES      | durable           | Consensus plans from ralplan (ADR-shaped).                       |
| `research/`     | YES      | durable           | Research reports from `omh-deep-research` (when shipped).        |

## Why selective sharing

A spec or a consensus plan is a **decision artifact** — the canonical record
of "what we agreed to build" or "how we agreed to build it." It belongs in
the repo for the same reason an ADR belongs in the repo: future contributors
need to know how we got here, and proposed changes to the goal/design should
go through PR review. Treating these as user-private throws that away.

State and logs are **per-session runtime**. They reflect what one developer
was doing at one moment, and they're cleared on completion. Sharing them
adds noise without value.

## Conventions for callers

- All paths are project-local. Never write to `~/.omh/` or any global
  location — `.omh/` lives next to the project it serves.
- `omh_state` writes use the atomic tmp→fsync→replace pattern. Manual JSON
  fallback (`json.dump` directly to `state/{mode}-state.json`) is acceptable
  when the plugin is unavailable, but use the tool when you can.
- Specs use `status: confirmed` in YAML frontmatter as the cross-skill
  sentinel. Plans and research reports follow the same convention.
- File naming is descriptive, not timestamped: `ralplan-{slug}-consensus.md`,
  not `ralplan-20260420.md`.

## Recursion note

When OMH is being developed *on itself* (i.e., the project rooted at this
repo IS the OMH source), the planning artifacts in `.omh/specs/` and
`.omh/plans/` are about OMH itself. That is intentional and correct — the
design records for OMH changes belong with the OMH source. Use a sibling
worktree (`git worktree add ../omh-work some-feature-branch`) if you want
to keep an independent `state/` from interfering with branch switches.
