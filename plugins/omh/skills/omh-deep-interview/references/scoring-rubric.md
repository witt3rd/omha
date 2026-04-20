# Coverage Scoring Rubric

Use this rubric to assess each dimension after the user answers. These are
coarse bins — don't over-think the boundary between bins. When in doubt,
round toward higher ambiguity (be conservative).

## Goal Clarity

| Bin | Description | Example |
|-----|-------------|---------|
| **HIGH** | User has a vague idea but can't articulate what they want | "I want something that helps with productivity" |
| **MEDIUM** | User can describe what they want but not why or for whom | "I want a CLI tool that tracks tasks" |
| **LOW** | Clear what, why, and who — minor details TBD | "A CLI task tracker for my personal use that syncs with my calendar" |
| **CLEAR** | Goal is specific, bounded, and actionable | "A Python CLI that reads tasks from a YAML file, shows today's items, and marks them done. For me only, no multi-user." |

## Constraint Clarity

| Bin | Description | Example |
|-----|-------------|---------|
| **HIGH** | No constraints mentioned or only vague ones | "It should be fast" |
| **MEDIUM** | Some constraints stated but gaps in key areas (tech stack, timeline, resources) | "Must be Python, should work on Linux" |
| **LOW** | Most constraints clear, one or two areas need pinning down | "Python 3.11+, Linux/macOS, no external services, MVP this week — not sure about data format yet" |
| **CLEAR** | All relevant constraints explicit and non-contradictory | "Python 3.11+, Linux/macOS, YAML config, no network calls, single file, done by Friday" |

## Success Criteria Clarity

| Bin | Description | Example |
|-----|-------------|---------|
| **HIGH** | No criteria defined or only feelings-based | "It should feel intuitive" |
| **MEDIUM** | Some criteria but not testable | "Users should be able to add tasks easily" |
| **LOW** | Mostly testable criteria with a few vague ones | "Can add/complete/list tasks from CLI; should handle 1000+ tasks — not sure about error cases" |
| **CLEAR** | All criteria are specific and testable | "add/complete/list/delete commands work; handles empty list; rejects duplicate IDs; loads 10K tasks in <1s" |

## Existing Context (Brownfield Only)

| Bin | Description | Example |
|-----|-------------|---------|
| **HIGH** | User mentions existing system but no specifics | "We have an API already" |
| **MEDIUM** | Some context about the existing system but unclear boundaries | "There's a REST API in FastAPI, uses Postgres" |
| **LOW** | Good understanding of the existing system, minor integration details TBD | "FastAPI app at /src/api/, Postgres with SQLAlchemy ORM, auth via JWT — not sure which endpoints we'd extend" |
| **CLEAR** | Existing system well-documented with clear integration points | "Extend /src/api/routes/tasks.py, add TaskModel to /src/models/, existing auth middleware handles permissions" |
| **N/A** | Greenfield project — no existing context | (skip this dimension) |

## Dimension Weights

Used internally to prioritize which dimension to probe next:

| Dimension | Greenfield Weight | Brownfield Weight |
|-----------|------------------|-------------------|
| Goal | 0.40 | 0.35 |
| Constraints | 0.30 | 0.25 |
| Success Criteria | 0.30 | 0.25 |
| Existing Context | — | 0.15 |

Higher weight = probe this dimension more aggressively when multiple dimensions are at the same bin level. Weights do NOT affect exit gating (exit is always user-confirmed).
