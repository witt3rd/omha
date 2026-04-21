"""
OMH State Engine — atomic read/write/cancel for .omh/state/{mode}-state.json.

All state files live under state_dir (default: .omh/state). Relative paths are
anchored against config["project_root"] if set, else against cwd at call time;
the result is always resolved to an absolute path so later cwd drift cannot
redirect writes.
Writes are atomic (write to .tmp.{uuid} → fsync → os.replace).
Every write wraps data in a _meta envelope: {written_at, mode, schema_version}.
Cancel is implemented as cancel_requested/cancel_reason/cancel_at fields
inside the mode's own state file — no separate cancel file.
"""

import json
import logging
import os
import re
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .omh_config import get_config

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_LIST_CACHE_TTL_SECONDS = 5.0

# Simple in-process cache for state_list_active (5-second TTL).
# NOTE: Not thread-safe — assumes single-threaded plugin execution (Hermes is single-threaded).
_list_cache: dict[str, Any] = {"result": None, "expires_at": 0.0}


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _seed_dot_omh(omh_dir: Path) -> None:
    """Drop README.md and .gitignore into .omh/ if missing.

    Idempotent: only writes files that don't exist. Templates ship with the
    plugin; user edits to the seeded files are preserved across runs.
    """
    seed_files = {
        "README.md": _TEMPLATES_DIR / "dot-omh-readme.md",
        ".gitignore": _TEMPLATES_DIR / "dot-omh-gitignore",
    }
    for dest_name, template_path in seed_files.items():
        dest = omh_dir / dest_name
        if dest.exists():
            continue
        try:
            dest.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to seed %s: %s", dest, e)


def _state_dir() -> Path:
    """Resolve the OMH state directory to an absolute path.

    Resolution order (mirrors evidence_tool.py):
      1. config["state_dir"] (defaults to ".omh/state").
      2. If relative, anchor against config["project_root"] if set,
         else against Path.cwd() at call time.
      3. Resolve to absolute so subsequent cwd drift cannot redirect writes.

    This prevents Bug 2 (state silently landing in ~/.omh/state/ when Hermes
    was started from $HOME, or wherever the agent's cwd happens to be).
    """
    config = get_config()
    p = Path(config.get("state_dir", ".omh/state"))
    if not p.is_absolute():
        project_root_cfg = config.get("project_root")
        base = Path(project_root_cfg).resolve() if project_root_cfg else Path.cwd().resolve()
        p = base / p
    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    _seed_dot_omh(p.parent)
    return p


def state_init() -> dict:
    """Explicitly create .omh/ in cwd and seed README.md + .gitignore.

    Idempotent — safe to run on an existing .omh/ directory; never overwrites
    user edits to seeded files. Reports which files were newly created.
    """
    seed_targets = ["README.md", ".gitignore"]
    omh_dir = Path(".omh")
    pre_existing = {name: (omh_dir / name).exists() for name in seed_targets}
    sd = _state_dir()  # triggers mkdir + seed
    seeded = [name for name in seed_targets if not pre_existing[name] and (omh_dir / name).exists()]
    return {
        "success": True,
        "omh_dir": str(omh_dir.resolve()),
        "state_dir": str(sd.resolve()),
        "seeded": seeded,
        "already_present": [name for name in seed_targets if pre_existing[name]],
    }


_MODE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _state_path(mode: str) -> Path:
    if not _MODE_RE.match(mode):
        raise ValueError(f"Invalid mode name: {mode!r} (only [a-zA-Z0-9_-] allowed)")
    return _state_dir() / f"{mode}-state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _wrap_meta(mode: str, data: dict) -> dict:
    # Strip only the reserved "_meta" key — other underscore-prefixed fields (e.g. _interrupted_at) are valid user data.
    clean_data = {k: v for k, v in data.items() if k != "_meta"}
    wrapped = {"_meta": {"written_at": _now_iso(), "mode": mode, "schema_version": _SCHEMA_VERSION, "written_by": "omh-plugin"}}
    wrapped.update(clean_data)
    return wrapped


def _is_stale(written_at: str, max_hours: float) -> bool:
    try:
        ts = datetime.fromisoformat(written_at)
        age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
        return age_seconds > max_hours * 3600
    except Exception:
        return True  # Unparseable timestamp → treat as stale


def _atomic_write(path: Path, content: str) -> None:
    """Write pre-serialized content atomically (write tmp → fsync → os.replace)."""
    tmp = path.with_suffix(f".tmp.{uuid.uuid4().hex}")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
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


def _invalidate_list_cache() -> None:
    _list_cache["expires_at"] = 0.0


def state_read(mode: str) -> dict:
    """Read .omh/state/{mode}-state.json.
    Returns {exists, data, stale, age_seconds}. Data stripped of _meta."""
    path = _state_path(mode)
    if not path.exists():
        return {"exists": False, "data": {}, "stale": False, "age_seconds": None}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"exists": True, "data": {}, "stale": True, "age_seconds": 0,
                "error": f"Parse error: {e}"}

    meta = raw.get("_meta", {})
    data = {k: v for k, v in raw.items() if k != "_meta"}
    file_version = meta.get("schema_version")
    if file_version is not None and file_version != _SCHEMA_VERSION:
        logger.warning("State file %s has schema_version=%s, expected %s", path, file_version, _SCHEMA_VERSION)
    written_at = meta.get("written_at", "")
    config = get_config()
    max_hours = config.get("staleness_hours", 2)
    stale = _is_stale(written_at, max_hours)

    age_seconds = 0
    if written_at:
        try:
            ts = datetime.fromisoformat(written_at)
            age_seconds = int((datetime.now(timezone.utc) - ts).total_seconds())
        except Exception:
            pass

    return {"exists": True, "data": data, "stale": stale, "age_seconds": age_seconds}


_STATE_WARN_SIZE = 100_000  # 100KB — warn but still write; large state may indicate a design issue

def state_write(mode: str, data: dict) -> dict:
    """Atomic write with _meta envelope. Returns {success, path}."""
    if not isinstance(data, dict):
        return {"success": False, "error": "data must be a dict"}
    path = _state_path(mode)
    wrapped = _wrap_meta(mode, data)
    try:
        serialized = json.dumps(wrapped, indent=2, ensure_ascii=False)
        if len(serialized) > _STATE_WARN_SIZE:
            logger.warning(
                "State for mode '%s' is large (%d bytes > %d byte threshold); "
                "consider offloading large data to a dedicated file.",
                mode, len(serialized), _STATE_WARN_SIZE,
            )
        _atomic_write(path, serialized)
        _invalidate_list_cache()
        return {"success": True, "path": str(path)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def state_clear(mode: str) -> dict:
    """Delete state file. Returns {cleared, path}."""
    path = _state_path(mode)
    if not path.exists():
        return {"cleared": True, "existed": False, "path": str(path)}
    try:
        path.unlink()
        _invalidate_list_cache()
        return {"cleared": True, "existed": True, "path": str(path)}
    except Exception as e:
        return {"cleared": False, "path": str(path), "error": str(e)}


def state_check(mode: str) -> dict:
    """Quick status: {exists, active, stale, phase, age_seconds, iteration}."""
    result = state_read(mode)
    data = result.get("data", {})
    check = {
        "exists": result["exists"],
        "active": bool(data.get("active")),
        "stale": result.get("stale", False),
        "phase": data.get("phase"),
        "age_seconds": result.get("age_seconds", 0),
        "iteration": data.get("iteration"),
    }
    if "error" in result:
        check["error"] = result["error"]
    return check


def state_list_active() -> dict:
    """List all modes with active state. Cached for 5 seconds."""
    now = time.monotonic()
    if _list_cache["result"] is not None and now < _list_cache["expires_at"]:
        return _list_cache["result"]

    state_dir = _state_dir()
    modes = []
    try:
        for p in sorted(state_dir.glob("*-state.json")):
            mode = p.stem.removesuffix("-state")
            check = state_check(mode)
            if check["exists"] and check["active"]:
                modes.append({"mode": mode, **check})
    except Exception as e:
        logger.warning("state_list_active error: %s", e)

    result = {"modes": modes}
    _list_cache["result"] = result
    _list_cache["expires_at"] = now + _LIST_CACHE_TTL_SECONDS
    return result


def state_cancel(mode: str, reason: str = "user request", requested_by: str = "user") -> dict:
    """Set cancel_requested=True in the mode's state file."""
    result = state_read(mode)
    if result["exists"]:
        data = result["data"]
    else:
        # Don't set active: True — avoids phantom active state in state_list_active().
        data = {}

    data["cancel_requested"] = True
    data["cancel_reason"] = reason
    data["cancel_at"] = _now_iso()
    data["cancel_requested_by"] = requested_by
    return state_write(mode, data)


def state_check_cancel(mode: str) -> dict:
    """Check if cancel_requested is set and within TTL. Clears expired signals."""
    result = state_read(mode)
    if not result["exists"]:
        return {"cancelled": False, "reason": None, "requested_at": None}

    data = result["data"]
    if not data.get("cancel_requested"):
        return {"cancelled": False, "reason": None, "requested_at": None}

    cancel_at = data.get("cancel_at", "")
    config = get_config()
    ttl = config.get("cancel_ttl_seconds", 30)

    expired = False
    if cancel_at:
        try:
            ts = datetime.fromisoformat(cancel_at)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            expired = age > ttl
        except Exception:
            pass

    if expired:
        data.pop("cancel_requested", None)
        data.pop("cancel_reason", None)
        data.pop("cancel_at", None)
        data.pop("cancel_requested_by", None)
        state_write(mode, data)
        return {"cancelled": False, "reason": None, "requested_at": None}

    return {
        "cancelled": True,
        "reason": data.get("cancel_reason"),
        "requested_at": cancel_at,
    }
