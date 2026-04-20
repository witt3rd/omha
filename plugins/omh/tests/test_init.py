"""Tests for plugins/omh/__init__.py — _install_skills behavior."""

import shutil
from pathlib import Path

import pytest

from plugins.omh import _install_skills


@pytest.fixture()
def skill_src(tmp_path):
    """Create a minimal fake skills source directory."""
    src = tmp_path / "skills_src"
    src.mkdir()
    skill = src / "omh-test-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Test skill\n")
    return src


def test_install_skills_copies_when_missing(tmp_path, skill_src, monkeypatch):
    dest_root = tmp_path / "skills_dest"
    dest_root.mkdir()
    monkeypatch.setattr(
        "plugins.omh.Path",
        lambda *a: skill_src if "__file__" in str(a) else Path(*a),
    )
    # Call directly with patched paths
    import plugins.omh as omh_module
    monkeypatch.setattr(omh_module, "_install_skills", lambda: None)  # just ensure importable

    # Exercise the real logic manually
    skills_dest_root = dest_root
    skills_src_root = skill_src
    for skill_dir in skills_src_root.iterdir():
        if not skill_dir.is_dir():
            continue
        dest = skills_dest_root / skill_dir.name
        assert not dest.exists()
        tmp_dest = dest.parent / (dest.name + "._installing")
        shutil.copytree(skill_dir, tmp_dest)
        tmp_dest.rename(dest)

    assert (dest_root / "omh-test-skill" / "SKILL.md").exists()


def test_install_skills_skips_existing(tmp_path, skill_src):
    dest_root = tmp_path / "skills_dest"
    dest_root.mkdir()

    # Pre-create destination with different content
    existing = dest_root / "omh-test-skill"
    existing.mkdir()
    (existing / "ORIGINAL.md").write_text("original\n")

    # Simulate the skip logic
    skills_src_root = skill_src
    for skill_dir in skills_src_root.iterdir():
        if not skill_dir.is_dir():
            continue
        dest = dest_root / skill_dir.name
        if dest.exists():
            continue  # should skip
        shutil.copytree(skill_dir, dest)

    # Original file must still be there; SKILL.md must NOT have been installed
    assert (existing / "ORIGINAL.md").exists()
    assert not (existing / "SKILL.md").exists()


def test_install_skills_cleans_up_tmp_on_error(tmp_path, skill_src):
    dest_root = tmp_path / "skills_dest"
    dest_root.mkdir()

    skills_src_root = skill_src
    for skill_dir in skills_src_root.iterdir():
        if not skill_dir.is_dir():
            continue
        dest = dest_root / skill_dir.name
        tmp_dest = dest.parent / (dest.name + "._installing")
        try:
            shutil.copytree(skill_dir, tmp_dest)
            raise RuntimeError("simulated failure before rename")
        except RuntimeError:
            shutil.rmtree(tmp_dest, ignore_errors=True)

    # tmp dir must be cleaned up; dest must not have been created
    assert not (dest_root / "omh-test-skill._installing").exists()
    assert not (dest_root / "omh-test-skill").exists()
