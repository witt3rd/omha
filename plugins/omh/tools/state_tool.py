"""
omh_state tool — unified state management for OMH workflow modes.

Actions:
  init         | scaffold .omh/ in cwd
  read/write/clear/check/cancel/cancel_check
                — singleton or per-instance (pass instance_id)
  list         | all active state files (singleton + per-instance)
  list_instances | enumerate all instances of a single mode
  lock         | acquire advisory lock (mode + lock_key)
  unlock       | release advisory lock
  lock_check   | inspect a lock without modifying
  load_role    | fetch a role prompt from the OMH catalog
"""

import json
import os

from ..omh_state import (
    state_cancel,
    state_check,
    state_check_cancel,
    state_clear,
    state_init,
    state_list_active,
    state_list_instances,
    state_lock_acquire,
    state_lock_check,
    state_lock_release,
    state_read,
    state_write,
)

OMH_STATE_SCHEMA = {
    "name": "omh_state",
    "description": (
        "Manage OMH workflow state. Singleton modes (one in-flight run) and "
        "per-instance modes (concurrent runs keyed by `instance_id`) share "
        "the same .omh/state/ directory. Pass `instance_id` for any concurrent "
        "mode (deep-research, deep-interview, ralph/autopilot when running "
        "multiple plans). Use `lock`/`unlock` advisory locks for state-mutating "
        "modes (ralph/autopilot) to prevent two sessions from racing on the "
        "same plan. Actions: init | read | write | clear | check | list | "
        "list_instances | cancel | cancel_check | lock | unlock | lock_check | "
        "load_role."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "init", "read", "write", "clear", "check",
                    "list", "list_instances",
                    "cancel", "cancel_check",
                    "lock", "unlock", "lock_check",
                    "load_role",
                ],
                "description": "Operation to perform",
            },
            "mode": {
                "type": "string",
                "description": (
                    "Mode name: ralph, autopilot, ralplan, deep-interview, "
                    "deep-research, etc. Required for everything except 'list', "
                    "'init', and 'load_role'."
                ),
            },
            "instance_id": {
                "type": "string",
                "description": (
                    "Optional per-instance key. When set, state is stored at "
                    ".omh/state/{mode}--{slug}.json so multiple sessions of the "
                    "same mode can coexist. Slug is derived from the input "
                    "(lowercased, [a-z0-9-] only, max 80 chars). Recommended "
                    "values: a topic slug for deep-research, a plan basename "
                    "for ralph/autopilot, an interview id for deep-interview. "
                    "Omit for singleton behavior (legacy)."
                ),
            },
            "data": {
                "type": "object",
                "description": "State data to write (action=write only)",
            },
            "reason": {
                "type": "string",
                "description": "Cancel reason (action=cancel only)",
            },
            "requested_by": {
                "type": "string",
                "description": "Who requested the cancel (action=cancel only, default: user)",
            },
            "lock_key": {
                "type": "string",
                "description": (
                    "Lock identifier for action=lock/unlock/lock_check. Should be "
                    "the resource being protected (e.g. plan path basename, goal "
                    "slug). Two sessions trying to acquire the same (mode, "
                    "lock_key) will serialize: only one wins, the other gets "
                    "{acquired: false, held_by: {...}}."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Owning session id stamped into the lockfile. Used by "
                    "action=unlock to verify the holder before release. "
                    "Recommended: pass a stable per-conversation id."
                ),
            },
            "holder_note": {
                "type": "string",
                "description": "Optional human-readable description of the lock holder.",
            },
            "force": {
                "type": "boolean",
                "description": "action=unlock only: bypass session_id check.",
            },
            "role": {
                "type": "string",
                "description": (
                    "Role name for load_role action (e.g. 'executor', 'verifier'). "
                    "Returns the full role prompt text from the OMH role catalog."
                ),
            },
        },
        "required": ["action"],
    },
}


def omh_state_handler(args: dict, **kwargs) -> str:
    action = args.get("action")
    mode = args.get("mode", "")
    instance_id = args.get("instance_id") or None

    if action == "list":
        return json.dumps(state_list_active())

    if action == "init":
        return json.dumps(state_init())

    if action == "load_role":
        role = args.get("role", "").strip()
        if not role:
            return json.dumps({"error": "role parameter is required for load_role"})
        from ..omh_roles import get_role_catalog, load_role_prompt
        prompt = load_role_prompt(role)
        if prompt is None:
            available = ", ".join(sorted(get_role_catalog().keys())) or "(none)"
            return json.dumps({"error": f"Unknown role '{role}'. Available: {available}"})
        return json.dumps({"role": role, "prompt": prompt})

    if not mode:
        return json.dumps({"error": "mode is required for this action"})

    # Lock actions need lock_key, not instance_id (orthogonal concept).
    if action in ("lock", "unlock", "lock_check"):
        lock_key = args.get("lock_key") or instance_id
        if not lock_key:
            return json.dumps({
                "error": f"lock_key is required for action={action} "
                         "(or pass instance_id as a fallback)"
            })
        session_id = args.get("session_id") or os.environ.get("HERMES_SESSION_ID") or ""
        try:
            if action == "lock":
                return json.dumps(state_lock_acquire(
                    mode, lock_key,
                    session_id=session_id,
                    holder_note=args.get("holder_note"),
                ))
            if action == "unlock":
                return json.dumps(state_lock_release(
                    mode, lock_key,
                    session_id=session_id,
                    force=bool(args.get("force")),
                ))
            return json.dumps(state_lock_check(mode, lock_key))
        except Exception as e:
            return json.dumps({"error": f"omh_state({action}, {mode}, {lock_key!r}) failed: {e}"})

    if action == "list_instances":
        try:
            return json.dumps(state_list_instances(mode))
        except Exception as e:
            return json.dumps({"error": f"omh_state(list_instances, {mode}) failed: {e}"})

    dispatch = {
        "read":         lambda: state_read(mode, instance_id),
        "write":        lambda: state_write(mode, args.get("data") or {}, instance_id),
        "clear":        lambda: state_clear(mode, instance_id),
        "check":        lambda: state_check(mode, instance_id),
        "cancel":       lambda: state_cancel(
            mode,
            args.get("reason", "user request"),
            args.get("requested_by", "user"),
            instance_id,
        ),
        "cancel_check": lambda: state_check_cancel(mode, instance_id),
    }

    fn = dispatch.get(action)
    if not fn:
        return json.dumps({"error": f"Unknown action: {action}"})

    try:
        return json.dumps(fn())
    except Exception as e:
        return json.dumps({"error": f"omh_state({action}, {mode}) failed: {e}"})
