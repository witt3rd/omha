"""
omh_state tool — unified state management for OMH workflow modes.

Actions: init | read | write | clear | check | list | cancel | cancel_check | load_role
"""

import json

from ..omh_state import (
    state_cancel,
    state_check,
    state_check_cancel,
    state_clear,
    state_init,
    state_list_active,
    state_read,
    state_write,
)

OMH_STATE_SCHEMA = {
    "name": "omh_state",
    "description": (
        "Manage OMH workflow state. Actions: "
        "init (scaffold .omh/ in cwd: create directory, seed README.md + .gitignore, idempotent), "
        "read (get current state), "
        "write (save state data), "
        "clear (delete state file), "
        "check (quick status: exists/active/stale/phase), "
        "list (all active OMH modes), "
        "cancel (request cancellation of a mode), "
        "cancel_check (check if cancellation was requested), "
        "load_role (load a role prompt by name, e.g. executor/verifier/architect). "
        "State is stored in .omh/state/ relative to the project root."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["init", "read", "write", "clear", "check", "list", "cancel", "cancel_check", "load_role"],
                "description": "Operation to perform",
            },
            "mode": {
                "type": "string",
                "description": (
                    "Mode name: ralph, autopilot, ralplan, deep-interview, etc. "
                    "Required for all actions except 'list'."
                ),
            },
            "data": {
                "type": "object",
                "description": "State data to write (for action=write only)",
            },
            "reason": {
                "type": "string",
                "description": "Cancel reason (for action=cancel only)",
            },
            "requested_by": {
                "type": "string",
                "description": "Who requested the cancel (for action=cancel only, default: user)",
            },
            "role": {
                "type": "string",
                "description": (
                    "Role name for load_role action (e.g. 'executor', 'verifier', 'architect'). "
                    "Returns the full role prompt text from the OMH plugin's role catalog."
                ),
            },
        },
        "required": ["action"],
    },
}


def omh_state_handler(args: dict, **kwargs) -> str:
    action = args.get("action")
    mode = args.get("mode", "")

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

    dispatch = {
        "read":         lambda: state_read(mode),
        "write":        lambda: state_write(mode, args.get("data") or {}),
        "clear":        lambda: state_clear(mode),
        "check":        lambda: state_check(mode),
        "cancel":       lambda: state_cancel(mode, args.get("reason", "user request"), args.get("requested_by", "user")),
        "cancel_check": lambda: state_check_cancel(mode),
    }

    fn = dispatch.get(action)
    if not fn:
        return json.dumps({"error": f"Unknown action: {action}"})

    try:
        return json.dumps(fn())
    except Exception as e:
        return json.dumps({"error": f"omh_state({action}, {mode}) failed: {e}"})
