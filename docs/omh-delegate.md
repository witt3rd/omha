# omh_delegate — hardened delegation wrapper (v0.2 — prepare/finalize split)

`omh_delegate` is a thin wrapper around Hermes's `delegate_task` that
hardens the parent-subagent boundary against output loss.

It addresses two failure modes observed in real usage:

- **FM1.** Parent loses subagent output mid-write (the original incident
  that motivated this work — 14.8 minutes of subagent reasoning gone).
- **FM2.** Subagent stalls on its own `write_file` and never returns.

## Design

v0 implements **pure subagent-persists** — the subagent is given a
deterministic output path via a brutal-prose contract block appended to
its goal, and is told that its final action MUST be `write_file` at that
exact path. The wrapper then verifies the file exists.

There is **no rescue branch in v0**. If the subagent ignores the
contract, the wrapper returns `ok=False` with the raw return preserved
on the completion breadcrumb — loud failure, not silent rescue. This is
deliberate: it preserves the feedback signal that teaches us whether the
contract prose works in practice. v1 may add a *loud* rescue branch
gated on measured contract-obedience (the C0 microbenchmark).

The full design history lives at
`.omh/research/ralplan-omh-delegate/` — spec, two rounds of
Planner / Architect / Critic debate, and the final consensus document.

## Public API — prepare / finalize (PRIMARY, for agent loops)

`delegate_task` is a Hermes **tool** invoked by the agent loop, not an
importable Python callable. The wrapper therefore splits into two
functions the agent calls *around* its own dispatch:

```python
from plugins.omh.omh_delegate import omh_delegate_prepare, omh_delegate_finalize

# Step 1 — prepare: compute paths, write dispatched breadcrumb, inject contract
prep = omh_delegate_prepare(
    role="planner",
    goal="<self-contained goal text>",
    mode="ralplan",
    phase="round1-planner",
    round=1,
    context="<optional context>",
)

# Step 2 — agent calls delegate_task as a tool (NOT shown in Python; this is
# the agent's own tool dispatch loop). Pass prep["augmented_goal"] and
# prep["context"]. The subagent will write to prep["expected_path"].
raw_return = ...  # whatever delegate_task returned (typically the path string)

# Step 3 — finalize: verify file present, write completion breadcrumb
result = omh_delegate_finalize(prep=prep, raw_return=raw_return)
# Or, if the dispatch raised:
# result = omh_delegate_finalize(prep=prep, error=f"{type(e).__name__}: {e}")
```

The split exists because the original `omh_delegate(...)` API assumed
`delegate_task` was importable as a Python callable. It isn't —
discovered during dogfood (Bug D1). The prepare/finalize API puts the
dispatch in the agent's hands where it belongs and keeps the wrapper in
charge of contract injection, breadcrumbs, and verification.

## Convenience API — single call (Python callers only)

For Python tests and integrations that have a real callable, the
all-in-one form still exists. It now requires explicit `delegate_fn=`
(passing `None` raises `TypeError` rather than falling through to a
broken default import — a regression guard for the Bug D1 failure mode).

```python
from plugins.omh.omh_delegate import omh_delegate

result = omh_delegate(
    role="planner",
    goal="<self-contained goal text>",
    mode="ralplan",
    phase="round1-planner",
    delegate_fn=my_real_python_callable,  # required, no default
    round=1,
    context="",
    toolsets=["file"],   # passthrough to delegate_fn
)
```

## Result schema

`omh_delegate_finalize(...)` and `omh_delegate(...)` both return:

```python
{
    "ok":                    bool,    # True iff file present and no error
    "ok_strict":             bool,    # AC-1 — see "Forward compatibility" below
    "path":                  str,     # absolute expected_output_path
    "id":                    str,     # dispatch id, used in breadcrumb filenames
    "file_present":          bool,    # source of truth
    "contract_satisfied":    bool,    # v0: == file_present
    "recovered_by_wrapper":  bool,    # always False in v0
    "raw":                   Any,     # raw return passed to finalize, unparsed
}
```

`omh_delegate_prepare(...)` returns:

```python
{
    "id":              str,    # pass to finalize via prep[]
    "expected_path":   str,    # absolute path the subagent must write to
    "augmented_goal":  str,    # goal + injected <<<EXPECTED_OUTPUT_PATH>>> contract
    "context":         str,    # echoed for convenience
    "breadcrumb_dir":  str,    # absolute, used by finalize
    "project_root":    str,
    "mode":            str,
    "phase":           str,
    "round":           int | None,
    "slug":            str | None,
    "role":            str,
}
```

## Path layout

Artifacts land at:

```
.omh/research/{mode}/{phase}[-r{round}][-{slug}]-{ts}.md
```

Breadcrumbs land at:

```
.omh/state/dispatched/{id}.dispatched.json   ← written by prepare()
.omh/state/dispatched/{id}.completed.json    ← written by finalize() (separate file)
```

Both breadcrumbs are **append-only**. The wrapper never mutates a
breadcrumb after writing it; completion data lives in a sibling file.
This eliminates a class of read-modify-write race conditions and
composes naturally with the project-wide atomic-write pattern.

## Project-root discovery

`omh_delegate` walks up from the current working directory looking for a
`.omh/` marker (mirroring how `git` discovers `.git/`). If no marker is
found, it falls back to cwd. Pass `project_root=Path(...)` to override.

## Forward compatibility (AC-1)

In v0 the `ok` field is a plain bool. v1.B may reintroduce a rescue
branch and make `ok` tri-state (`True | False | "degraded"`). Python
truthiness will treat the string `"degraded"` as truthy, so naïve
callers writing `if result["ok"]:` would silently treat a degraded
result as success.

To stay correct across that future change, callers needing a hard
pass/fail check should use `ok_strict`:

```python
if result["ok_strict"]:        # always exactly True / False
    ...
```

`ok_strict` is shipped in v0 even though it is currently identical to
`ok` — the schema is forward-stable.

## Known limitations (v0)

These are intentional v0 simplifications, deferred to later phases.
They are documented here so the deferrals are explicit and discoverable
rather than silently inherited.

- **No batch dispatch helper.** v0 is single-task only at the wrapper
  level. The agent can call `delegate_task(tasks=[...])` between prepare
  and finalize; v1 will add a batch-aware wrapper.
- **No rescue branch.** Contract violations surface as `ok=False` with
  the raw return preserved on the completion breadcrumb. v1 may add a
  loud, sentinel-marker-gated rescue if the C0 measurement shows it is
  warranted (file_present rate between 80% and 95%).
- **No recovery CLI.** v2 ships `omh_recover --list / --gc / --from-id`.
  Until then, breadcrumbs are inspectable manually under
  `.omh/state/dispatched/`.
- **Cross-filesystem `os.replace` is not handled (AC-2).** If `.omh/`
  lives on a different filesystem from where Python's tempfile would
  land (e.g., `.omh/` on a FUSE mount inside a Docker container),
  `os.replace` from the temp location to the final path will raise
  `OSError: [Errno 18] Invalid cross-device link`. v0 surfaces this as
  a clear error; v2 will add startup detection plus a non-atomic
  fallback. In practice, the wrapper writes its tmp file as
  `path.with_suffix(...".tmp.{uuid}")` *next to* the final destination,
  so the failure mode only triggers if the final destination's parent
  itself straddles a filesystem boundary — rare in normal repos.
- **No goal preview in breadcrumbs.** Only `goal_sha256` and
  `goal_bytes` are stored. This avoids leaking secrets that may bleed
  through into goal text. v1 may add an opt-in scrubbed preview.
- **No silent degrade.** If `.omh/` is unwritable, the wrapper raises.
  There is no `allow_degrade=True` knob in v0.
- **Single-orchestrator assumption.** v0 assumes one writer per
  `.omh/state/dispatched/`. Multi-orchestrator deployments are a v2
  concern; the append-only breadcrumb design will accommodate them
  with minimal additional locking.

## Tests

`plugins/omh/tests/test_omh_delegate.py` covers:

1. Happy path — subagent obeys contract (orchestrator form).
2. Contract violation — no rescue, raw preserved on breadcrumb.
3. `delegate_task` raises — breadcrumb captures error, exception re-raised.
4. Project-root walk-up from a nested subdirectory.
5. Project-root falls back to cwd when no `.omh/` marker exists.
6. Three-boolean status always present.
7. Append-only breadcrumbs (separate files, no RMW).
8. `prepare()` returns augmented goal + writes dispatched breadcrumb only.
9. `finalize()` happy path with file present.
10. `finalize()` contract violation — no file at expected path.
11. `finalize()` with explicit error — recorded on breadcrumb, no re-raise.
12. `omh_delegate(delegate_fn=None)` raises `TypeError` (Bug D1 regression guard).
13. Orchestrator end-to-end: same end-state as explicit prepare/finalize.

## Roadmap

- **v0** (initial) — minimal wrapper, no rescue, single-task, dogfood on
  one ralplan phase. Single all-in-one API with a broken default import.
- **v0.2** (this) — prepare/finalize split as primary API; orchestrator
  becomes a Python-only convenience that requires explicit `delegate_fn`.
  Bug D1 fix.
- **v1.A** (always) — extract `omh_io` helpers, add batch dispatch
  helper, Hermes tool registration, migrate remaining ralplan phases and
  the other OMH skills.
- **v1.B** (conditional on C0 measurement) — sentinel-marker-gated
  loud rescue branch with three-boolean status surfaced as
  `ok="degraded"`.
- **v2** — recovery CLI, GC, session_id capture, lock sentinel for
  multi-orchestrator, cross-fs detection.

