"""Tests for plugins/omh/__init__.py — _link_skills() and register() behavior."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_ctx():
    return MagicMock()


# ---------------------------------------------------------------------------
# _link_skills() — symlink creation and ownership logic
# ---------------------------------------------------------------------------

class TestLinkSkills:
    def test_creates_symlink_when_missing(self, tmp_path):
        """Creates a symlink in dest when nothing exists there."""
        src_root = tmp_path / "src"
        dest_root = tmp_path / "dest"
        (src_root / "omh-ralplan").mkdir(parents=True)

        from plugins.omh import _link_skills
        _link_skills(src_root, dest_root)

        link = dest_root / "omh-ralplan"
        assert link.is_symlink()
        assert link.resolve() == (src_root / "omh-ralplan").resolve()

    def test_refreshes_our_own_symlink(self, tmp_path):
        """Replaces an existing symlink that already points into our tree."""
        src_root = tmp_path / "src"
        dest_root = tmp_path / "dest"
        dest_root.mkdir()
        (src_root / "omh-ralph").mkdir(parents=True)

        dest = dest_root / "omh-ralph"
        dest.symlink_to((src_root / "omh-ralph").resolve())

        from plugins.omh import _link_skills
        _link_skills(src_root, dest_root)

        assert dest.is_symlink()
        assert dest.resolve() == (src_root / "omh-ralph").resolve()

    def test_recreates_broken_our_symlink(self, tmp_path):
        """Recreates a broken symlink whose name has the omh- prefix."""
        src_root = tmp_path / "src"
        dest_root = tmp_path / "dest"
        dest_root.mkdir()
        (src_root / "omh-autopilot").mkdir(parents=True)

        # Broken symlink pointing nowhere
        dest = dest_root / "omh-autopilot"
        dest.symlink_to(tmp_path / "nonexistent" / "omh-autopilot")
        assert dest.is_symlink() and not dest.exists()

        from plugins.omh import _link_skills
        _link_skills(src_root, dest_root)

        assert dest.is_symlink()
        assert dest.resolve() == (src_root / "omh-autopilot").resolve()

    def test_skips_real_directory(self, tmp_path):
        """Never touches a real directory — user owns it."""
        src_root = tmp_path / "src"
        dest_root = tmp_path / "dest"
        (src_root / "omh-ralplan").mkdir(parents=True)
        user_dir = dest_root / "omh-ralplan"
        user_dir.mkdir(parents=True)
        (user_dir / "MY_CUSTOM_FILE.md").write_text("user content")

        from plugins.omh import _link_skills
        _link_skills(src_root, dest_root)

        assert user_dir.is_dir() and not user_dir.is_symlink()
        assert (user_dir / "MY_CUSTOM_FILE.md").read_text() == "user content"

    def test_skips_foreign_symlink(self, tmp_path):
        """Does not replace a symlink pointing somewhere outside our tree."""
        src_root = tmp_path / "src"
        dest_root = tmp_path / "dest"
        elsewhere = tmp_path / "elsewhere" / "omh-ralplan"
        elsewhere.mkdir(parents=True)
        (src_root / "omh-ralplan").mkdir(parents=True)

        dest_root.mkdir()
        dest = dest_root / "omh-ralplan"
        dest.symlink_to(elsewhere.resolve())

        from plugins.omh import _link_skills
        _link_skills(src_root, dest_root)

        assert Path(os.readlink(dest)).resolve() == elsewhere.resolve()

    def test_creates_dest_root_if_missing(self, tmp_path):
        """Creates the destination directory if it doesn't exist."""
        src_root = tmp_path / "src"
        dest_root = tmp_path / "dest" / "skills"  # nested, not yet created
        (src_root / "omh-ralplan").mkdir(parents=True)

        from plugins.omh import _link_skills
        _link_skills(src_root, dest_root)

        assert dest_root.is_dir()
        assert (dest_root / "omh-ralplan").is_symlink()

    def test_links_all_bundled_skills(self, tmp_path):
        """All five bundled skills are linked."""
        src_root = tmp_path / "src"
        dest_root = tmp_path / "dest"
        skills = ["omh-ralplan", "omh-ralph", "omh-deep-interview",
                  "omh-deep-research", "omh-autopilot"]
        for s in skills:
            (src_root / s).mkdir(parents=True)

        from plugins.omh import _link_skills
        _link_skills(src_root, dest_root)

        for s in skills:
            link = dest_root / s
            assert link.is_symlink(), f"{s} should be a symlink"
            assert link.resolve() == (src_root / s).resolve()


# ---------------------------------------------------------------------------
# register() — tools and hooks (link_skills patched out to avoid real fs)
# ---------------------------------------------------------------------------

def test_register_tools():
    ctx = _make_ctx()
    from plugins.omh import register
    with patch("plugins.omh._link_skills"):
        register(ctx)
    names = {c.args[0] for c in ctx.register_tool.call_args_list}
    assert names == {"omh_state", "omh_gather_evidence"}
    for c in ctx.register_tool.call_args_list:
        assert c.args[1] == "omh"


def test_register_hooks():
    ctx = _make_ctx()
    from plugins.omh import register
    with patch("plugins.omh._link_skills"):
        register(ctx)
    names = {c.args[0] for c in ctx.register_hook.call_args_list}
    assert names == {"pre_llm_call", "on_session_end", "pre_tool_call"}


def test_register_tool_and_hook_counts():
    ctx = _make_ctx()
    from plugins.omh import register
    with patch("plugins.omh._link_skills"):
        register(ctx)
    assert ctx.register_tool.call_count == 2
    assert ctx.register_hook.call_count == 3
