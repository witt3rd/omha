"""
OMH Plugin — infrastructure layer for Oh My Hermes skills.

Registers:
  Tools: omh_state, omh_gather_evidence
  Hooks: pre_llm_call, on_session_end, pre_tool_call
  Skills: omh-ralplan, omh-ralph, omh-deep-interview, omh-autopilot (bundled)
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_TOOLSET = "omh"


def _install_skills():
    """Install bundled skills to ~/.hermes/skills/ if not already present.

    Skips skills that are already installed — the user's copy takes precedence.
    Uses an atomic copy-then-rename pattern to avoid partial installs.
    """
    try:
        from hermes_cli.config import get_hermes_home
        skills_dest_root = get_hermes_home() / "skills"
    except Exception:
        skills_dest_root = Path.home() / ".hermes" / "skills"

    skills_src_root = Path(__file__).parent / "skills"
    if not skills_src_root.exists():
        return

    skills_dest_root.mkdir(parents=True, exist_ok=True)

    for skill_dir in skills_src_root.iterdir():
        if not skill_dir.is_dir():
            continue
        dest = skills_dest_root / skill_dir.name
        if dest.exists():
            continue  # already installed; never overwrite user's copy
        tmp_dest = dest.parent / (dest.name + "._installing")
        try:
            if tmp_dest.exists():
                shutil.rmtree(tmp_dest)
            shutil.copytree(skill_dir, tmp_dest)
            tmp_dest.rename(dest)  # atomic on same filesystem
        except Exception as e:
            logger.warning("Failed to install skill '%s': %s", skill_dir.name, e)
            shutil.rmtree(tmp_dest, ignore_errors=True)


def register(ctx):
    """Entry point called by Hermes plugin discovery."""
    _install_skills()

    from .tools.state_tool import OMH_STATE_SCHEMA, omh_state_handler
    from .tools.evidence_tool import OMH_EVIDENCE_SCHEMA, omh_evidence_handler
    from .hooks.llm_hooks import pre_llm_call
    from .hooks.session_hooks import on_session_end
    from .hooks.tool_hooks import pre_tool_call

    ctx.register_tool("omh_state", _TOOLSET, OMH_STATE_SCHEMA, omh_state_handler,
                       description=OMH_STATE_SCHEMA["description"])
    ctx.register_tool("omh_gather_evidence", _TOOLSET, OMH_EVIDENCE_SCHEMA, omh_evidence_handler,
                       description=OMH_EVIDENCE_SCHEMA["description"])
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("on_session_end", on_session_end)
    ctx.register_hook("pre_tool_call", pre_tool_call)
