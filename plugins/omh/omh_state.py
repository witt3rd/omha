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
_INSTANCE_RAW_MAX = 200          # reject anything obviously absurd
_INSTANCE_SLUG_MAX = 80          # post-slugification cap


def _slugify_instance(raw: str) -> str:
    """Normalize an instance_id to a filesystem-safe slug.

    Lowercase, [a-z0-9-] only, collapse runs of dashes, strip leading/trailing
    dashes, cap at 80 chars. Raises ValueError if the input is empty after
    normalization (caller should fall back to default singleton path).
    """
    if not isinstance(raw, str):
        raise ValueError(f"instance_id must be a string, got {type(raw).__name__}")
    if len(raw) > _INSTANCE_RAW_MAX:
        raise ValueError(f"instance_id too long ({len(raw)} chars > {_INSTANCE_RAW_MAX})")
    s = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not s:
        raise ValueError(f"instance_id {raw!r} normalizes to empty slug")
    return s[:_INSTANCE_SLUG_MAX].strip("-")


def _state_path(mode: str, instance_id: str | None = None) -> Path:
    if not _MODE_RE.match(mode):
        raise ValueError(f"Invalid mode name: {mode!r} (only [a-zA-Z0-9_-] allowed)")
    if instance_id is None:
        return _state_dir() / f"{mode}-state.json"
    slug = _slugify_instance(instance_id)
    # NOTE: '--' separator chosen so per-instance files can be unambiguously
    # parsed even when mode names contain '-' (e.g. deep-research, deep-interview).
    # _slugify_instance collapses runs of '-' to single '-', so '--' never
    # appears inside slug.
    return _state_dir() / f"{mode}--{slug}.json"


def _lock_path(mode: str, lock_key: str) -> Path:
    if not _MODE_RE.match(mode):
        raise ValueError(f"Invalid mode name: {mode!r} (only [a-zA-Z0-9_-] allowed)")
    slug = _slugify_instance(lock_key)
    return _state_dir() / f"{mode}--{slug}.lock"


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid exists. Best-effort, POSIX only."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else — treat as alive.
        return True
    except Exception:
        return False


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


def state_read(mode: str, instance_id: str | None = None) -> dict:
    """Read .omh/state/{mode}-state.json (or {mode}-{instance_id}.json).
    Returns {exists, data, stale, age_seconds}. Data stripped of _meta."""
    path = _state_path(mode, instance_id)
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

def state_write(mode: str, data: dict, instance_id: str | None = None) -> dict:
    """Atomic write with _meta envelope. Returns {success, path}."""
    if not isinstance(data, dict):
        return {"success": False, "error": "data must be a dict"}
    path = _state_path(mode, instance_id)
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


def state_clear(mode: str, instance_id: str | None = None) -> dict:
    """Delete state file. Returns {cleared, path}."""
    path = _state_path(mode, instance_id)
    if not path.exists():
        return {"cleared": True, "existed": False, "path": str(path)}
    try:
        path.unlink()
        _invalidate_list_cache()
        return {"cleared": True, "existed": True, "path": str(path)}
    except Exception as e:
        return {"cleared": False, "path": str(path), "error": str(e)}


def state_check(mode: str, instance_id: str | None = None) -> dict:
    """Quick status: {exists, active, stale, phase, age_seconds, iteration}."""
    result = state_read(mode, instance_id)
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
    """List all active state files across all modes/instances. Cached for 5 seconds.

    Discovers both singleton files ({mode}-state.json) and per-instance files
    ({mode}-{instance_id}.json). For per-instance files, the listed entry
    includes both `mode` and `instance_id`.
    """
    now = time.monotonic()
    if _list_cache["result"] is not None and now < _list_cache["expires_at"]:
        return _list_cache["result"]

    state_dir = _state_dir()
    modes = []
    try:
        for p in sorted(state_dir.glob("*.json")):
            stem = p.stem
            # Per-instance: {mode}--{instance_id} (check first; '--' is unambiguous)
            if "--" in stem:
                mode, _, instance_id = stem.partition("--")
                if not _MODE_RE.match(mode) or not instance_id:
                    continue
                check = state_check(mode, instance_id)
                if check["exists"] and check["active"]:
                    modes.append({"mode": mode, "instance_id": instance_id, **check})
                continue
            # Singleton: {mode}-state
            if stem.endswith("-state"):
                mode = stem[:-len("-state")]
                if not _MODE_RE.match(mode):
                    continue
                check = state_check(mode)
                if check["exists"] and check["active"]:
                    modes.append({"mode": mode, **check})
                continue
    except Exception as e:
        logger.warning("state_list_active error: %s", e)

    result = {"modes": modes}
    _list_cache["result"] = result
    _list_cache["expires_at"] = now + _LIST_CACHE_TTL_SECONDS
    return result


def state_list_instances(mode: str) -> dict:
    """List all instance state files for a given mode.

    Returns {instances: [{instance_id, exists, active, stale, phase, age_seconds, iteration}, ...]}.
    Includes the singleton (instance_id=None) if it exists. Does not check the
    'active' flag — use state_list_active() for that filter.
    """
    if not _MODE_RE.match(mode):
        raise ValueError(f"Invalid mode name: {mode!r}")
    state_dir = _state_dir()
    out = []
    try:
        # Singleton
        singleton = state_dir / f"{mode}-state.json"
        if singleton.exists():
            out.append({"instance_id": None, **state_check(mode)})
        # Per-instance — match {mode}--*.json
        for p in sorted(state_dir.glob(f"{mode}--*.json")):
            stem = p.stem
            instance_id = stem[len(mode) + 2:]  # +2 to skip '--'
            if not instance_id:
                continue
            out.append({"instance_id": instance_id, **state_check(mode, instance_id)})
    except Exception as e:
        logger.warning("state_list_instances(%s) error: %s", mode, e)
    return {"mode": mode, "instances": out}


def state_cancel(mode: str, reason: str = "user request", requested_by: str = "user",
                 instance_id: str | None = None) -> dict:
    """Set cancel_requested=True in the mode's state file."""
    result = state_read(mode, instance_id)
    if result["exists"]:
        data = result["data"]
    else:
        # Don't set active: True — avoids phantom active state in state_list_active().
        data = {}

    data["cancel_requested"] = True
    data["cancel_reason"] = reason
    data["cancel_at"] = _now_iso()
    data["cancel_requested_by"] = requested_by
    return state_write(mode, data, instance_id)


def state_check_cancel(mode: str, instance_id: str | None = None) -> dict:
    """Check if cancel_requested is set and within TTL. Clears expired signals."""
    result = state_read(mode, instance_id)
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
        state_write(mode, data, instance_id)
        return {"cancelled": False, "reason": None, "requested_at": None}

    return {
        "cancelled": True,
        "reason": data.get("cancel_reason"),
        "requested_at": cancel_at,
    }


# ---------------------------------------------------------------------------
# Advisory locks (used by ralph/autopilot to prevent concurrent runs on the
# same plan/goal). Lockfile format is JSON: {pid, session_id, started_at,
# instance_id?, holder_note?}.
# ---------------------------------------------------------------------------


def state_lock_acquire(mode: str, lock_key: str, session_id: str | None = None,
                       holder_note: str | None = None) -> dict:
    """Acquire an advisory lock keyed on (mode, lock_key).

    Returns:
      {"acquired": True, "path": ...} on success.
      {"acquired": False, "held_by": {pid, session_id, started_at, ...}, "stale": bool, "path": ...}
        when another holder has the lock.

    Stale locks (pid no longer alive) are auto-released and the acquire retries
    once. Lock file content is the same JSON envelope as state files (with _meta).
    """
    path = _lock_path(mode, lock_key)
    payload = {
        "pid": os.getpid(),
        "session_id": session_id or "",
        "started_at": _now_iso(),
        "lock_key": lock_key,
    }
    if holder_note:
        payload["holder_note"] = holder_note

    for attempt in range(2):
        # O_EXCL: atomic create-or-fail
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                         stat.S_IRUSR | stat.S_IWUSR)
        except FileExistsError:
            existing = _read_lock(path)
            held_pid = int(existing.get("pid") or 0)
            if held_pid and not _pid_alive(held_pid):
                # Stale lock — remove and retry once.
                logger.warning("Removing stale lock %s (pid=%d not alive)", path, held_pid)
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                if attempt == 0:
                    continue
            return {
                "acquired": False,
                "held_by": existing,
                "stale": False,
                "path": str(path),
            }
        else:
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                return {"acquired": True, "path": str(path), "holder": payload}
            except Exception as e:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
                return {"acquired": False, "error": str(e), "path": str(path)}
    # Should be unreachable.
    return {"acquired": False, "path": str(path), "error": "lock acquire exhausted retries"}


def _read_lock(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def state_lock_release(mode: str, lock_key: str, session_id: str | None = None,
                       force: bool = False) -> dict:
    """Release an advisory lock.

    By default only releases if the holder's session_id matches (or the holder's
    pid is dead). Pass force=True to override (used by `cancel`/admin paths).
    """
    path = _lock_path(mode, lock_key)
    if not path.exists():
        return {"released": True, "existed": False, "path": str(path)}
    holder = _read_lock(path)
    holder_sid = holder.get("session_id") or ""
    holder_pid = int(holder.get("pid") or 0)
    if not force:
        if session_id and holder_sid and session_id != holder_sid:
            if holder_pid and _pid_alive(holder_pid):
                return {
                    "released": False,
                    "path": str(path),
                    "held_by": holder,
                    "error": "session_id mismatch and holder is alive; pass force=True to override",
                }
    try:
        path.unlink()
        return {"released": True, "existed": True, "path": str(path), "prior_holder": holder}
    except Exception as e:
        return {"released": False, "path": str(path), "error": str(e)}


def state_lock_check(mode: str, lock_key: str) -> dict:
    """Inspect a lock without modifying it. Returns {held, holder, stale, path}."""
    path = _lock_path(mode, lock_key)
    if not path.exists():
        return {"held": False, "holder": None, "stale": False, "path": str(path)}
    holder = _read_lock(path)
    pid = int(holder.get("pid") or 0)
    stale = bool(pid) and not _pid_alive(pid)
    return {"held": True, "holder": holder, "stale": stale, "path": str(path)}
