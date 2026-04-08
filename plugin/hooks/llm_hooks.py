"""
pre_llm_call hook — inject OMH mode awareness into each conversation turn.

On the first turn of a session: full context listing all active modes.
On subsequent turns: brief reminder with current mode/phase/iteration.
Returns None when no OMH modes are active (zero overhead).
"""

import logging

from ..omh_state import state_list_active

logger = logging.getLogger(__name__)


def pre_llm_call(**kwargs) -> dict | None:
    """Inject OMH mode context before each LLM call."""
    try:
        active = state_list_active()
    except Exception as e:
        logger.debug("pre_llm_call: state_list_active error: %s", e)
        return None

    if not active.get("modes"):
        return None

    # Hermes is expected to inject is_first_turn=True on the opening call of each session.
    # If this kwarg is absent the first-turn full-context branch silently degrades to the
    # brief reminder. Log at debug level so operators can detect the contract mismatch.
    is_first_turn = kwargs.get("is_first_turn", False)
    if not is_first_turn and "is_first_turn" not in kwargs:
        logger.debug(
            "pre_llm_call: 'is_first_turn' kwarg not provided by Hermes runtime; "
            "first-turn full-context branch inactive for this call"
        )

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
        return {"context": "\n".join(lines)}
    else:
        modes = active["modes"]
        if len(modes) == 1:
            mode = modes[0]
            mode_str = f"{mode['mode']} (phase: {mode.get('phase') or '?'})"
        else:
            parts = [f"{m['mode']}:{m.get('phase') or '?'}" for m in modes]
            mode_str = ", ".join(parts)
        first_mode = modes[0]["mode"]
        return {"context": (
            f"[OMH] Active: {mode_str}. "
            f"Use omh_state(action='cancel_check', mode='{first_mode}') "
            f"to check for cancellation before continuing. "
            f"Use omh_state(action='read', mode='<mode>') to reload state if needed."
        )}
