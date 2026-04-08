"""
on_session_end hook — mark active OMH modes with an interruption timestamp.

When Hermes exits while OMH modes are active, writes _interrupted_at to
their state files so the next session knows it was interrupted mid-workflow.
"""

import logging
from datetime import datetime, timezone

from ..omh_state import _invalidate_list_cache, state_list_active, state_read, state_write

logger = logging.getLogger(__name__)


def on_session_end(**kwargs) -> None:
    """Write _interrupted_at to all active OMH state files."""
    try:
        _invalidate_list_cache()  # Force fresh disk scan — avoids stale 5s cache at session boundary
        active = state_list_active()
    except Exception as e:
        logger.debug("on_session_end: state_list_active error: %s", e)
        return

    modes = active.get("modes", [])
    if not modes:
        return

    interrupted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saved = []

    for m in modes:
        mode_name = m["mode"]
        try:
            result = state_read(mode_name)
            if not result.get("exists"):
                continue
            data = result["data"]
            if not data.get("active"):
                continue
            data["_interrupted_at"] = interrupted_at
            state_write(mode_name, data)
            saved.append(mode_name)
        except Exception as e:
            logger.warning("on_session_end: failed to save %s: %s", mode_name, e)

    if saved:
        logger.info("OMH: saved interruption state for modes: %s", saved)
