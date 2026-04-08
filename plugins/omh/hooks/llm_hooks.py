"""
pre_llm_call hook — inject OMH mode awareness and role prompts into each turn.

On the first turn of a session:
  - If user_message contains an [omh-role:NAME] marker: inject the full role prompt.
  - If OMH modes are active: inject full context listing all active modes.
On subsequent turns: brief reminder with current mode/phase/iteration.
Returns None when neither role markers nor active modes are present (zero overhead).
"""

import logging

from ..omh_roles import extract_role_marker, load_role_prompt
from ..omh_state import state_list_active

logger = logging.getLogger(__name__)


def pre_llm_call(**kwargs) -> dict | None:
    """Inject role prompt and/or OMH mode context before each LLM call."""
    is_first_turn = kwargs.get("is_first_turn", False)
    if not is_first_turn and "is_first_turn" not in kwargs:
        logger.debug(
            "pre_llm_call: 'is_first_turn' kwarg not provided by Hermes runtime; "
            "first-turn full-context branch inactive for this call"
        )

    context_parts = []

    # --- Role prompt injection (first turn only) ---
    if is_first_turn:
        user_message = kwargs.get("user_message", "") or ""
        role_name = extract_role_marker(user_message)
        if role_name is not None:
            role_prompt = load_role_prompt(role_name)
            if role_prompt is not None:
                context_parts.append(f"[OMH Role: {role_name}]\n{role_prompt}")
            else:
                from ..omh_roles import get_role_catalog
                available = ", ".join(sorted(get_role_catalog().keys())) or "(none)"
                logger.warning(
                    "pre_llm_call: unknown role '%s' requested via marker. Available: %s",
                    role_name, available,
                )
                context_parts.append(
                    f"[OMH WARNING] Unknown role '{role_name}' requested. "
                    f"Available roles: {available}. No role prompt was injected."
                )

    # --- Mode awareness injection ---
    try:
        active = state_list_active()
    except Exception as e:
        logger.debug("pre_llm_call: state_list_active error: %s", e)
        active = {}

    if active.get("modes"):
        if is_first_turn:
            lines = ["[OMH] Active modes detected — read state before proceeding:"]
            for m in active["modes"]:
                age = m.get("age_seconds", "?")
                phase = m.get("phase") or "?"
                lines.append(f"  - {m['mode']}: phase={phase}, age={age}s")
            lines.append(
                "Use omh_state(action='read', mode='<mode>') to load current state "
                "and continue from where you left off."
            )
            context_parts.append("\n".join(lines))
        else:
            modes = active["modes"]
            if len(modes) == 1:
                mode = modes[0]
                mode_str = f"{mode['mode']} (phase: {mode.get('phase') or '?'})"
            else:
                parts = [f"{m['mode']}:{m.get('phase') or '?'}" for m in modes]
                mode_str = ", ".join(parts)
            first_mode = modes[0]["mode"]
            context_parts.append(
                f"[OMH] Active: {mode_str}. "
                f"Use omh_state(action='cancel_check', mode='{first_mode}') "
                f"to check for cancellation before continuing. "
                f"Use omh_state(action='read', mode='<mode>') to reload state if needed."
            )

    if not context_parts:
        return None
    return {"context": "\n\n".join(context_parts)}
