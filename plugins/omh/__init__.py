"""
OMH Plugin — infrastructure layer for Oh My Hermes skills.

Registers:
  Tools: omh_state, omh_gather_evidence
  Hooks: pre_llm_call, on_session_end, pre_tool_call
  Skills: omh-ralplan, omh-ralph, omh-deep-interview, omh-autopilot, omh-deep-research
          Installed as symlinks in ~/.hermes/skills/ pointing back into the plugin's
          own skills/ directory. Updates are picked up automatically on next session.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_TOOLSET = "omh"

# Prefix that marks skills owned by this plugin.
# We will only touch symlinks (never real dirs) whose name starts with this.
_SKILL_PREFIX = "omh-"


def _is_our_symlink(dest: Path, src: Path) -> bool:
    """Return True if dest is a symlink that points into our plugin's skills/ tree."""
    if not dest.is_symlink():
        return False
    try:
        target = Path(os.readlink(dest))
        if not target.is_absolute():
            target = (dest.parent / target).resolve()
        return target == src.resolve() or src.resolve() in target.parents
    except Exception:
        return False


def _is_broken_our_symlink(dest: Path) -> bool:
    """Return True if dest is a broken symlink with our prefix (stale, was ours)."""
    return dest.is_symlink() and not dest.exists() and dest.name.startswith(_SKILL_PREFIX)


def _link_skills(
    skills_src_root: "Path | None" = None,
    skills_dest_root: "Path | None" = None,
) -> None:
    """Create or refresh symlinks in ~/.hermes/skills/ for each bundled skill.

    Ownership rules:
    - dest does not exist          -> create symlink
    - dest is a symlink to us      -> refresh (replace) in case plugin path changed
    - dest is a broken symlink
      with our prefix              -> we owned it, recreate
    - dest is a real directory     -> user owns it, skip (never overwrite)
    - dest is a symlink elsewhere  -> user owns it, skip

    The optional *skills_src_root* and *skills_dest_root* arguments override the
    default paths and are used by tests to avoid touching the real filesystem.
    """
    if skills_dest_root is None:
        try:
            from hermes_cli.config import get_hermes_home
            skills_dest_root = get_hermes_home() / "skills"
        except Exception:
            skills_dest_root = Path.home() / ".hermes" / "skills"

    if skills_src_root is None:
        skills_src_root = Path(__file__).parent / "skills"

    if not skills_src_root.exists():
        return

    skills_dest_root.mkdir(parents=True, exist_ok=True)

    for skill_src in skills_src_root.iterdir():
        if not skill_src.is_dir():
            continue
        dest = skills_dest_root / skill_src.name

        if dest.is_symlink():
            if _is_our_symlink(dest, skill_src) or _is_broken_our_symlink(dest):
                # Ours — refresh the symlink (handles plugin path changes)
                dest.unlink()
            else:
                # Points somewhere else — not ours, leave it
                logger.debug("omh: skipping %s — symlink to unknown target", dest.name)
                continue
        elif dest.exists():
            # Real directory — user owns it, never touch
            logger.debug("omh: skipping %s — real directory exists", dest.name)
            continue

        try:
            dest.symlink_to(skill_src.resolve())
            logger.debug("omh: linked skill %s -> %s", dest.name, skill_src.resolve())
        except Exception as e:
            logger.warning("omh: failed to link skill '%s': %s", skill_src.name, e)


def register(ctx):
    """Entry point called by Hermes plugin discovery."""
    _link_skills()

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
