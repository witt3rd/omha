"""
pre_tool_call hook — validate [omh-role:NAME] markers in delegate_task calls.

Intercepts delegate_task tool calls in the parent session and warns when
an [omh-role:NAME] marker references an unknown role. This is defense-in-depth:
the hook catches typos at delegation time (fail-fast) before the subagent starts.

The hook is non-blocking: it warns but does not prevent the delegate_task call.
The pre_llm_call hook in the subagent session handles actual role prompt injection.
"""

import json
import logging

logger = logging.getLogger(__name__)


def pre_tool_call(**kwargs) -> dict | None:
    """Warn on unknown [omh-role:NAME] markers in delegate_task goal strings."""
    if kwargs.get("tool_name") != "delegate_task":
        return None

    tool_input = kwargs.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except Exception:
            return None

    goal = tool_input.get("goal", "")
    if not goal:
        return None

    from ..omh_roles import extract_role_marker, get_role_catalog
    role_name = extract_role_marker(goal)
    if role_name is None:
        return None

    catalog = get_role_catalog()
    if role_name not in catalog:
        available = ", ".join(sorted(catalog.keys())) or "(none)"
        logger.warning(
            "omh pre_tool_call: unknown role '%s' in delegate_task goal. "
            "Available: %s",
            role_name,
            available,
        )
        return {
            "context": (
                f"[OMH WARNING] Unknown role '{role_name}' in delegate_task goal. "
                f"Available roles: {available}. "
                "The subagent will not receive a role prompt injection."
            )
        }

    return None
