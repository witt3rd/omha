"""
omh_delegate — hardened wrapper around delegate_task (prepare/finalize split).

PRIMARY API (v0.2): two functions the agent calls around its own dispatch.

  prep = omh_delegate_prepare(role=..., mode=..., phase=..., goal=..., context=...)
  raw  = delegate_task(goal=prep["augmented_goal"], context=prep["context"], ...)
  res  = omh_delegate_finalize(prep=prep, raw_return=raw)

Why split: delegate_task is a Hermes TOOL invoked by the agent loop, not a
Python callable importable from this module. The original v0 single-call API
assumed otherwise and crashed at import time (Bug D1, surfaced 2026-04-21
during deep-research dogfood). Splitting puts the dispatch in the agent's
hands where it belongs; the wrapper retains ownership of: path computation,
contract injection, breadcrumbs, and verification.

CONVENIENCE API: omh_delegate(...) — Python callable orchestrator. Requires
explicit delegate_fn= injection. Used by tests and Python-side integrations
that have a real callable to pass. NOT usable from inside an agent loop.

Behavior (unchanged from v0):
  1. Discover project root via .omh/ walk-up (mirrors git). (W4)
  2. Compute deterministic expected_output_path under
     .omh/research/{mode}/{phase}[-r{round}][-{slug}]-{ts}.md
  3. mkdir parents.
  4. Write {id}.dispatched.json breadcrumb (atomic, append-only — no RMW).
  5. Inject brutal-prose <<<EXPECTED_OUTPUT_PATH>>> contract appended to goal.
  6. (agent dispatches; wrapper does NOT parse the return)
  7. Check Path(expected_output_path).is_file().
  8. Write {id}.completed.json breadcrumb (separate file, single-write).
  9. Return {ok, ok_strict, path, id, file_present, contract_satisfied,
            recovered_by_wrapper, raw}.

AC-1: ok_strict = (ok is True). Callers needing hard pass/fail should check
      ok_strict, not ok. v1.B may make ok tri-state ("degraded"); Python
      truthiness would treat that as truthy. ok_strict is forward-compatible.

AC-2: cross-fs os.replace failure (FUSE/Docker volumes) is not handled;
      see plugin README §"Known limitations" for the v2 deferral.
"""

import hashlib
import json
import logging
import os
import secrets
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Helpers (inlined in v0; v1.A1/A2 will extract to omh_io)
# ---------------------------------------------------------------------------


def _discover_project_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) looking for a .omh/ marker.

    Mirrors git's .git discovery. Returns the directory CONTAINING .omh/.
    Falls back to start (or cwd) if no .omh/ found.
    """
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".omh").is_dir():
            return candidate
    return cur


def _atomic_write_text(path: Path, content: str) -> None:
    """Write content to path atomically (tmp → fsync → os.replace).

    Mirrors omh_state._atomic_write. AC-2: cross-fs (e.g. .omh/ on a
    different filesystem from $TMPDIR) failures will surface as OSError
    from os.replace; v0 does not auto-detect or fall back.
    """
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex}")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_compact() -> str:
    """UTC timestamp for filenames: YYYYMMDDTHHMMSSZ."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Path / id computation
# ---------------------------------------------------------------------------


def _compute_expected_path(
    project_root: Path,
    mode: str,
    phase: str,
    round: int | None,
    slug: str | None,
    ts: str,
) -> Path:
    """.omh/research/{mode}/{phase}[-r{round}][-{slug}]-{ts}.md (absolute)."""
    parts = [phase]
    if round is not None:
        parts.append(f"r{round}")
    if slug:
        parts.append(slug)
    parts.append(ts)
    filename = "-".join(parts) + ".md"
    return (project_root / ".omh" / "research" / mode / filename).resolve()


def _compute_id(mode: str, phase: str, round: int | None, ts: str) -> str:
    """{mode}-{phase}[-r{round}]-{ts}-{rand4}."""
    parts = [mode, phase]
    if round is not None:
        parts.append(f"r{round}")
    parts.append(ts)
    parts.append(secrets.token_hex(2))  # 4 hex chars
    return "-".join(parts)


# ---------------------------------------------------------------------------
# Goal injection
# ---------------------------------------------------------------------------


_CONTRACT_TEMPLATE = """

---

<<<EXPECTED_OUTPUT_PATH>>>
{expected_path}
<<<END_EXPECTED_OUTPUT_PATH>>>

CRITICAL contract — your final action MUST be exactly:

  write_file('{expected_path}', <full content as markdown>)

And your return value MUST be exactly the string:

  {expected_path}

The file you write IS the deliverable. The path is the receipt. Do not
summarize or paraphrase the deliverable in your return value. Do not write
to any other path. Do not URL-encode, expand ~, or change the extension.
"""


def _inject_contract(goal: str, expected_path: Path) -> str:
    """Append the brutal-prose contract to the goal text (M4: appended)."""
    return goal.rstrip() + _CONTRACT_TEMPLATE.format(expected_path=str(expected_path))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def omh_delegate_prepare(
    *,
    role: str,
    goal: str,
    mode: str,
    phase: str,
    context: str = "",
    round: int | None = None,
    slug: str | None = None,
    project_root: Path | None = None,
) -> dict:
    """Phase 1 of the wrapper: compute paths, write dispatched breadcrumb,
    inject the contract into the goal text, and return everything the agent
    needs to perform the dispatch itself.

    Returns dict:
      {
        "id":              dispatch id,
        "expected_path":   absolute path the subagent must write to,
        "augmented_goal":  goal text with <<<EXPECTED_OUTPUT_PATH>>> contract appended,
        "context":         passed-through context (echoed for convenience),
        "breadcrumb_dir":  absolute path where breadcrumbs live,
        "project_root":    discovered project root (absolute),
        "mode":            echoed,
        "phase":           echoed,
        "round":           echoed,
        "slug":            echoed,
        "role":            echoed,
      }

    Pass the result dict to omh_delegate_finalize(prep=..., raw_return=...)
    after performing the dispatch with delegate_task.
    """
    root = (project_root.resolve() if project_root else _discover_project_root())
    ts = _now_compact()
    expected_path = _compute_expected_path(root, mode, phase, round, slug, ts)
    dispatch_id = _compute_id(mode, phase, round, ts)

    expected_path.parent.mkdir(parents=True, exist_ok=True)
    breadcrumb_dir = (root / ".omh" / "state" / "dispatched").resolve()
    breadcrumb_dir.mkdir(parents=True, exist_ok=True)

    goal_bytes = goal.encode("utf-8")
    dispatched = {
        "_meta": {
            "written_at": _now_iso(),
            "schema_version": _SCHEMA_VERSION,
            "kind": "dispatch",
        },
        "id": dispatch_id,
        "mode": mode,
        "phase": phase,
        "round": round,
        "slug": slug,
        "role": role,
        "dispatched_at": _now_iso(),
        "expected_output_path": str(expected_path),
        "goal_sha256": hashlib.sha256(goal_bytes).hexdigest(),
        "goal_bytes": len(goal_bytes),
        "context_bytes": len(context.encode("utf-8")),
    }
    dispatched_path = breadcrumb_dir / f"{dispatch_id}.dispatched.json"
    _atomic_write_text(dispatched_path, json.dumps(dispatched, indent=2))

    augmented_goal = _inject_contract(goal, expected_path)

    return {
        "id": dispatch_id,
        "expected_path": str(expected_path),
        "augmented_goal": augmented_goal,
        "context": context,
        "breadcrumb_dir": str(breadcrumb_dir),
        "project_root": str(root),
        "mode": mode,
        "phase": phase,
        "round": round,
        "slug": slug,
        "role": role,
    }


def omh_delegate_finalize(
    *,
    prep: dict,
    raw_return: Any = None,
    error: str | None = None,
) -> dict:
    """Phase 2: verify file presence, write completion breadcrumb, return
    the structured result.

    Pass the dict returned by omh_delegate_prepare as `prep`. Pass whatever
    the dispatch returned as `raw_return` (may be None or any JSON-able
    value; arbitrary objects are repr'd). If the dispatch raised, pass the
    exception message as `error` (do not also re-raise here — caller handles
    that).
    """
    expected_path = Path(prep["expected_path"])
    breadcrumb_dir = Path(prep["breadcrumb_dir"])
    dispatch_id = prep["id"]

    file_present = expected_path.is_file()
    bytes_ = expected_path.stat().st_size if file_present else 0

    _write_completion_breadcrumb(
        breadcrumb_dir=breadcrumb_dir,
        dispatch_id=dispatch_id,
        file_present=file_present,
        contract_satisfied=file_present,  # v0: identity. v1.B may differ.
        recovered_by_wrapper=False,        # always False in v0.
        bytes_=bytes_,
        raw_return=raw_return,
        error=error,
    )

    if error is not None:
        _emit_warning(dispatch_id, expected_path, error="exception",
                      detail=error)
    elif not file_present:
        _emit_warning(dispatch_id, expected_path, error="contract_violation",
                      detail="file not present at expected path after dispatch")

    ok = file_present and (error is None)
    return {
        "ok": ok,
        "ok_strict": (ok is True),  # AC-1
        "path": str(expected_path),
        "id": dispatch_id,
        "file_present": file_present,
        "contract_satisfied": file_present,
        "recovered_by_wrapper": False,
        "raw": raw_return,
    }


def omh_delegate(
    *,
    role: str,
    goal: str,
    mode: str,
    phase: str,
    delegate_fn: Any,
    context: str = "",
    round: int | None = None,
    slug: str | None = None,
    project_root: Path | None = None,
    **passthrough,
) -> dict:
    """Convenience orchestrator for Python callers with a real delegate_fn.

    Equivalent to:
        prep = omh_delegate_prepare(...)
        try:
            raw = delegate_fn(goal=prep["augmented_goal"],
                              context=prep["context"], **passthrough)
        except Exception as exc:
            omh_delegate_finalize(prep=prep, error=f"{type(exc).__name__}: {exc}")
            raise
        return omh_delegate_finalize(prep=prep, raw_return=raw)

    NOT usable from inside an agent loop because Hermes' delegate_task is a
    tool, not an importable Python callable. Agent loops should call
    omh_delegate_prepare → delegate_task (via the agent's tool dispatch) →
    omh_delegate_finalize directly.

    AC-1: callers needing hard pass/fail should check `ok_strict`, not `ok`.
    """
    if delegate_fn is None:
        raise TypeError(
            "omh_delegate(...) requires an explicit delegate_fn= callable. "
            "From inside an agent loop, use omh_delegate_prepare/finalize "
            "around the agent's own delegate_task tool dispatch."
        )

    prep = omh_delegate_prepare(
        role=role, goal=goal, mode=mode, phase=phase, context=context,
        round=round, slug=slug, project_root=project_root,
    )

    try:
        raw_return = delegate_fn(
            goal=prep["augmented_goal"],
            context=prep["context"],
            **passthrough,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        omh_delegate_finalize(prep=prep, raw_return=None, error=error)
        raise

    return omh_delegate_finalize(prep=prep, raw_return=raw_return)


# ---------------------------------------------------------------------------
# Internal: completion breadcrumb writer
# ---------------------------------------------------------------------------


_RAW_RETURN_CAP_BYTES = 8192


def _summarize_raw_return(raw: Any) -> tuple[str, str]:
    """Return (raw_return_kind, serialized_raw_capped_at_8KB).

    Kind is 'string' | 'dict' | 'none' | 'other'. Serialized form is a
    string suitable for JSON storage; truncated with marker if over cap.
    """
    if raw is None:
        return ("none", "")
    if isinstance(raw, str):
        kind = "string"
        text = raw
    elif isinstance(raw, dict):
        kind = "dict"
        try:
            text = json.dumps(raw, indent=2, default=str)
        except Exception:
            text = repr(raw)
    else:
        kind = "other"
        try:
            text = json.dumps(raw, default=str)
        except Exception:
            text = repr(raw)
    if len(text.encode("utf-8")) > _RAW_RETURN_CAP_BYTES:
        text = text.encode("utf-8")[:_RAW_RETURN_CAP_BYTES].decode(
            "utf-8", errors="replace"
        ) + "\n...[truncated at 8KB]"
    return (kind, text)


def _write_completion_breadcrumb(
    *,
    breadcrumb_dir: Path,
    dispatch_id: str,
    file_present: bool,
    contract_satisfied: bool,
    recovered_by_wrapper: bool,
    bytes_: int,
    raw_return: Any,
    error: str | None,
) -> None:
    kind, serialized = _summarize_raw_return(raw_return)
    completion = {
        "_meta": {
            "written_at": _now_iso(),
            "schema_version": _SCHEMA_VERSION,
            "kind": "completed",
        },
        "id": dispatch_id,
        "completed_at": _now_iso(),
        "file_present": file_present,
        "contract_satisfied": contract_satisfied,
        "recovered_by_wrapper": recovered_by_wrapper,
        "bytes": bytes_,
        "raw_return_kind": kind,
        "raw_return": serialized,
        "error": error,
    }
    completion_path = breadcrumb_dir / f"{dispatch_id}.completed.json"
    _atomic_write_text(completion_path, json.dumps(completion, indent=2))


def _emit_warning(dispatch_id: str, expected_path: Path, *, error: str, detail: str) -> None:
    """W5: one-line stderr warning on any non-clean dispatch."""
    msg = (
        f"omh_delegate[{error}]: id={dispatch_id} expected={expected_path} "
        f"detail={detail!r}"
    )
    print(msg, file=sys.stderr, flush=True)
