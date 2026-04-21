"""Tests for omh_state.py — state engine and omh_state_handler dispatch."""

import json
import logging
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import plugins.omh.omh_config as omh_config_module
from plugins.omh.omh_state import (
    state_cancel,
    state_check,
    state_check_cancel,
    state_clear,
    state_list_active,
    state_read,
    state_write,
)
from plugins.omh.tools.state_tool import omh_state_handler


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point state_dir at a temp directory and reset config cache."""
    monkeypatch.chdir(tmp_path)
    omh_config_module._config_cache = {
        "state_dir": ".omh/state",
        "staleness_hours": 2,
        "cancel_ttl_seconds": 30,
        "evidence": {},
    }
    from plugins.omh import omh_state as mod
    mod._list_cache["result"] = None
    mod._list_cache["expires_at"] = 0.0
    yield
    omh_config_module._config_cache = None
    mod._list_cache["result"] = None
    mod._list_cache["expires_at"] = 0.0


# ---------------------------------------------------------------------------
# Round-trip write/read/clear
# ---------------------------------------------------------------------------

def test_write_creates_file():
    result = state_write("ralph", {"active": True, "phase": "execute", "iteration": 1})
    assert result["success"] is True
    path = Path(".omh/state/ralph-state.json")
    assert path.exists()


def test_state_dir_creation_seeds_dot_omh_readme_and_gitignore():
    """First write to .omh/ should drop README.md and .gitignore from templates."""
    state_write("ralph", {"active": True})
    readme = Path(".omh/README.md")
    gitignore = Path(".omh/.gitignore")
    assert readme.exists(), "expected .omh/README.md to be seeded"
    assert gitignore.exists(), "expected .omh/.gitignore to be seeded"
    assert "selective sharing" in readme.read_text()
    assert "state/" in gitignore.read_text()


# ---------------------------------------------------------------------------
# Bug 2 — state_dir resolves to project_root, not transient cwd
# ---------------------------------------------------------------------------

def test_state_dir_uses_project_root_not_cwd(tmp_path, monkeypatch):
    """Relative state_dir must anchor to project_root config, not cwd-at-call.

    Reproduces Bug 2 from omh-self-flakiness.md: when project_root is set but
    the agent's cwd has drifted elsewhere, state must still land in the
    project's .omh/state/ directory.
    """
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    omh_config_module._config_cache = {
        "state_dir": ".omh/state",
        "project_root": str(project_root),
        "staleness_hours": 2,
        "cancel_ttl_seconds": 30,
        "evidence": {},
    }
    state_write(mode="ralph", data={"x": 1})
    assert (project_root / ".omh" / "state" / "ralph-state.json").exists()
    assert not (elsewhere / ".omh" / "state" / "ralph-state.json").exists()


def test_state_dir_falls_back_to_cwd_when_project_root_unset(tmp_path, monkeypatch):
    """Without project_root, relative state_dir resolves against cwd-at-call."""
    monkeypatch.chdir(tmp_path)
    omh_config_module._config_cache = {
        "state_dir": ".omh/state",
        "staleness_hours": 2,
        "cancel_ttl_seconds": 30,
        "evidence": {},
    }
    state_write(mode="ralph", data={"x": 1})
    assert (tmp_path / ".omh" / "state" / "ralph-state.json").exists()


def test_state_dir_absolute_path_used_as_is(tmp_path, monkeypatch):
    """Absolute state_dir must be honored verbatim, ignoring project_root."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    abs_state = tmp_path / "external-state"
    monkeypatch.chdir(tmp_path)
    omh_config_module._config_cache = {
        "state_dir": str(abs_state),
        "project_root": str(project_root),
        "staleness_hours": 2,
        "cancel_ttl_seconds": 30,
        "evidence": {},
    }
    state_write(mode="ralph", data={"x": 1})
    assert (abs_state / "ralph-state.json").exists()
    assert not (project_root / ".omh" / "state" / "ralph-state.json").exists()


def test_state_dir_immune_to_cwd_drift_after_first_call(tmp_path, monkeypatch):
    """Once resolved, subsequent cwd changes must not redirect state writes."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    drift_target = tmp_path / "drifted"
    drift_target.mkdir()
    monkeypatch.chdir(project_root)
    omh_config_module._config_cache = {
        "state_dir": ".omh/state",
        "project_root": str(project_root),
        "staleness_hours": 2,
        "cancel_ttl_seconds": 30,
        "evidence": {},
    }
    state_write(mode="ralph", data={"phase": "first"})
    monkeypatch.chdir(drift_target)
    state_write(mode="ralph", data={"phase": "second"})
    final = json.loads((project_root / ".omh" / "state" / "ralph-state.json").read_text())
    assert final["phase"] == "second"
    assert not (drift_target / ".omh" / "state" / "ralph-state.json").exists()


def test_seed_does_not_overwrite_user_edits():
    """If user has already customized .omh/README.md, don't clobber it."""
    Path(".omh").mkdir(exist_ok=True)
    custom = "# my project's custom .omh notes\n"
    Path(".omh/README.md").write_text(custom)
    state_write("ralph", {"active": True})
    assert Path(".omh/README.md").read_text() == custom


def test_init_scaffolds_fresh_dot_omh():
    """state_init on a clean cwd creates .omh/, seeds README + .gitignore, reports both."""
    from plugins.omh.omh_state import state_init
    result = state_init()
    assert result["success"] is True
    assert Path(".omh").is_dir()
    assert Path(".omh/README.md").exists()
    assert Path(".omh/.gitignore").exists()
    assert sorted(result["seeded"]) == [".gitignore", "README.md"]
    assert result["already_present"] == []


def test_init_is_idempotent_and_reports_already_present():
    """Running init twice doesn't re-seed; second run reports files as already present."""
    from plugins.omh.omh_state import state_init
    state_init()
    custom = "# user-edited\n"
    Path(".omh/README.md").write_text(custom)
    result = state_init()
    assert result["seeded"] == []
    assert sorted(result["already_present"]) == [".gitignore", "README.md"]
    assert Path(".omh/README.md").read_text() == custom


def test_init_via_handler_returns_json():
    """The omh_state tool routes action=init correctly."""
    result = json.loads(omh_state_handler({"action": "init"}))
    assert result["success"] is True
    assert "omh_dir" in result
    assert "seeded" in result


def test_read_returns_data_without_meta():
    state_write("ralph", {"active": True, "phase": "execute"})
    result = state_read("ralph")
    assert result["exists"] is True
    assert result["data"]["active"] is True
    assert result["data"]["phase"] == "execute"
    assert "_meta" not in result["data"]


def test_read_missing_file():
    result = state_read("nonexistent")
    assert result["exists"] is False
    assert result["data"] == {}
    assert result["age_seconds"] is None


def test_write_rejects_non_dict():
    # Test with string
    result = state_write("ralph", "not a dict")
    assert result["success"] is False
    assert "data must be a dict" in result["error"]

    # Test with list
    result = state_write("ralph", ["also", "not", "a", "dict"])
    assert result["success"] is False
    assert "data must be a dict" in result["error"]


def test_clear_removes_file():
    state_write("ralph", {"active": True})
    result = state_clear("ralph")
    assert result["cleared"] is True
    assert result["existed"] is True
    assert not Path(".omh/state/ralph-state.json").exists()


def test_clear_missing_file():
    result = state_clear("nonexistent")
    assert result["cleared"] is True
    assert result["existed"] is False


# ---------------------------------------------------------------------------
# _meta envelope
# ---------------------------------------------------------------------------

def test_meta_envelope_present():
    state_write("ralph", {"active": True})
    raw = json.loads(Path(".omh/state/ralph-state.json").read_text())
    assert "_meta" in raw
    assert raw["_meta"]["mode"] == "ralph"
    assert raw["_meta"]["schema_version"] == 1
    assert "written_at" in raw["_meta"]
    assert raw["_meta"]["written_by"] == "omh-plugin"


# ---------------------------------------------------------------------------
# state_check
# ---------------------------------------------------------------------------

def test_check_active():
    state_write("ralph", {"active": True, "phase": "verify"})
    check = state_check("ralph")
    assert check["exists"] is True
    assert check["active"] is True
    assert check["phase"] == "verify"


def test_check_missing():
    check = state_check("nomode")
    assert check["exists"] is False
    assert check["active"] is False


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

def test_staleness_not_stale():
    state_write("ralph", {"active": True})
    result = state_read("ralph")
    assert result["stale"] is False


def test_staleness_detected(monkeypatch):
    # Write a state file with a very old written_at
    state_write("ralph", {"active": True})
    path = Path(".omh/state/ralph-state.json")
    raw = json.loads(path.read_text())
    raw["_meta"]["written_at"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(raw))

    result = state_read("ralph")
    assert result["stale"] is True
    assert result["age_seconds"] > 0


# ---------------------------------------------------------------------------
# Cancel signal lifecycle
# ---------------------------------------------------------------------------

def test_cancel_sets_field():
    state_write("ralph", {"active": True})
    result = state_cancel("ralph", reason="test cancel", requested_by="test-agent")
    assert result["success"] is True

    read = state_read("ralph")
    assert read["data"]["cancel_requested"] is True
    assert read["data"]["cancel_reason"] == "test cancel"
    assert read["data"]["cancel_requested_by"] == "test-agent"


def test_cancel_check_detects_signal():
    state_write("ralph", {"active": True})
    state_cancel("ralph", reason="user abort")
    result = state_check_cancel("ralph")
    assert result["cancelled"] is True
    assert result["reason"] == "user abort"


def test_cancel_check_no_signal():
    state_write("ralph", {"active": True})
    result = state_check_cancel("ralph")
    assert result["cancelled"] is False


def test_cancel_check_expired(monkeypatch):
    omh_config_module._config_cache["cancel_ttl_seconds"] = 0  # TTL = 0s → always expired
    state_write("ralph", {"active": True})
    state_cancel("ralph", requested_by="test-agent")
    time.sleep(0.01)
    result = state_check_cancel("ralph")
    assert result["cancelled"] is False
    # All cancel fields including cancel_requested_by must be cleared from state
    data = state_read("ralph")["data"]
    assert "cancel_requested" not in data
    assert "cancel_reason" not in data
    assert "cancel_at" not in data
    assert "cancel_requested_by" not in data


def test_cancel_without_existing_state():
    # cancel on a mode with no state file should still work
    result = state_cancel("ralph", reason="preemptive")
    assert result["success"] is True
    check = state_check_cancel("ralph")
    assert check["cancelled"] is True


def test_cancel_without_existing_state_no_phantom_active():
    # ARCH-004: state_cancel on a non-existent mode must not create phantom active state
    state_cancel("ghost-mode", reason="preemptive")
    from plugins.omh import omh_state as mod
    mod._list_cache["expires_at"] = 0  # force cache miss
    result = state_list_active()
    mode_names = [m["mode"] for m in result["modes"]]
    assert "ghost-mode" not in mode_names


# ---------------------------------------------------------------------------
# state_list_active
# ---------------------------------------------------------------------------

def test_list_active_empty():
    result = state_list_active()
    assert result["modes"] == []


def test_list_active_shows_active_modes():
    state_write("ralph", {"active": True, "phase": "execute"})
    state_write("autopilot", {"active": False, "phase": "complete"})

    from plugins.omh import omh_state as mod
    mod._list_cache["expires_at"] = 0  # invalidate cache

    result = state_list_active()
    mode_names = [m["mode"] for m in result["modes"]]
    assert "ralph" in mode_names
    assert "autopilot" not in mode_names


# ---------------------------------------------------------------------------
# Atomic write — basic crash safety (no partial writes visible)
# ---------------------------------------------------------------------------

def test_atomic_write_no_tmp_left():
    state_write("ralph", {"active": True})
    state_dir = Path(".omh/state")
    tmp_files = list(state_dir.glob("*.tmp.*"))
    assert tmp_files == [], f"Leftover tmp files: {tmp_files}"


# ---------------------------------------------------------------------------
# omh_state_handler — dispatch table coverage
# ---------------------------------------------------------------------------

def test_handler_read():
    state_write("ralph", {"active": True, "phase": "execute"})
    result = json.loads(omh_state_handler({"action": "read", "mode": "ralph"}))
    assert result["exists"] is True
    assert result["data"]["phase"] == "execute"


def test_handler_write():
    result = json.loads(omh_state_handler({"action": "write", "mode": "ralph", "data": {"active": True}}))
    assert result["success"] is True


def test_handler_check():
    state_write("ralph", {"active": True, "phase": "verify"})
    result = json.loads(omh_state_handler({"action": "check", "mode": "ralph"}))
    assert result["active"] is True
    assert result["phase"] == "verify"


def test_handler_clear():
    state_write("ralph", {"active": True})
    result = json.loads(omh_state_handler({"action": "clear", "mode": "ralph"}))
    assert result["cleared"] is True


def test_handler_list():
    state_write("ralph", {"active": True})
    from plugins.omh import omh_state as mod
    mod._list_cache["expires_at"] = 0
    result = json.loads(omh_state_handler({"action": "list"}))
    assert "modes" in result
    assert any(m["mode"] == "ralph" for m in result["modes"])


def test_handler_cancel():
    state_write("ralph", {"active": True})
    result = json.loads(omh_state_handler({"action": "cancel", "mode": "ralph", "reason": "test"}))
    assert result["success"] is True


def test_handler_cancel_check():
    state_write("ralph", {"active": True})
    state_cancel("ralph")
    result = json.loads(omh_state_handler({"action": "cancel_check", "mode": "ralph"}))
    assert result["cancelled"] is True


def test_handler_missing_mode_returns_error():
    result = json.loads(omh_state_handler({"action": "read"}))
    assert "error" in result
    assert "mode" in result["error"]


def test_handler_unknown_action_returns_error():
    result = json.loads(omh_state_handler({"action": "explode", "mode": "ralph"}))
    assert "error" in result
    assert "Unknown action" in result["error"]


def test_handler_invalid_mode_caught():
    # Path traversal attempt — _state_path raises ValueError, handler catches it
    result = json.loads(omh_state_handler({"action": "read", "mode": "../etc/passwd"}))
    assert "error" in result


# ---------------------------------------------------------------------------
# _list_cache — cache hit path
# ---------------------------------------------------------------------------

def test_list_active_cache_hit_returns_stale_result():
    state_write("ralph", {"active": True})
    first = state_list_active()
    # Write a second mode directly to disk (bypassing state_write) so the
    # in-process cache is NOT invalidated — simulating a write from another process.
    import json as _json
    from plugins.omh import omh_state as mod
    Path(".omh/state").mkdir(parents=True, exist_ok=True)
    Path(".omh/state/autopilot-state.json").write_text(
        _json.dumps({"_meta": {"written_at": mod._now_iso(), "mode": "autopilot",
                                "schema_version": 1}, "active": True}),
        encoding="utf-8",
    )
    # Cache is still warm — should serve the cached result
    second = state_list_active()
    assert first == second
    mode_names = [m["mode"] for m in second["modes"]]
    assert "autopilot" not in mode_names  # not visible yet


def test_list_active_cache_invalidated_after_write():
    state_write("ralph", {"active": True})
    state_list_active()  # populate cache
    state_write("autopilot", {"active": True})  # should invalidate
    from plugins.omh import omh_state as mod
    assert mod._list_cache["expires_at"] == 0.0  # write calls _invalidate_list_cache


# ---------------------------------------------------------------------------
# _is_stale — unparseable timestamp
# ---------------------------------------------------------------------------

def test_staleness_unparseable_timestamp_returns_true():
    state_write("ralph", {"active": True})
    path = Path(".omh/state/ralph-state.json")
    raw = json.loads(path.read_text())
    raw["_meta"]["written_at"] = "not-a-timestamp"
    path.write_text(json.dumps(raw))
    result = state_read("ralph")
    assert result["stale"] is True


# ---------------------------------------------------------------------------
# state_read — corrupt JSON
# ---------------------------------------------------------------------------

def test_read_corrupt_json_returns_error_key():
    Path(".omh/state").mkdir(parents=True, exist_ok=True)
    Path(".omh/state/ralph-state.json").write_text("{not valid json")
    result = state_read("ralph")
    assert result["exists"] is True
    assert result["stale"] is True
    assert "error" in result


# ---------------------------------------------------------------------------
# _atomic_write — failure cleans up temp file
# ---------------------------------------------------------------------------

def test_atomic_write_cleans_tmp_on_replace_failure(monkeypatch):
    import os
    original_replace = os.replace
    def fail_replace(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", fail_replace)
    result = state_write("ralph", {"active": True})
    assert result["success"] is False
    assert "error" in result
    # No .tmp.* files should remain
    state_dir = Path(".omh/state")
    if state_dir.exists():
        tmp_files = list(state_dir.glob("*.tmp.*"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# Unicode payload roundtrip
# ---------------------------------------------------------------------------

def test_state_data_with_unicode_roundtrips():
    state_write("ralph", {"note": "状態 émoji 🔥", "active": True})
    result = state_read("ralph")
    assert result["data"]["note"] == "状態 émoji 🔥"


# ---------------------------------------------------------------------------
# _meta envelope — user data with _meta key is stripped
# ---------------------------------------------------------------------------

def test_write_strips_user_meta_key():
    state_write("ralph", {"active": True, "_meta": {"written_at": "2099-01-01T00:00:00+00:00"}})
    result = state_read("ralph")
    # The _meta envelope should have the real written_at, not the attacker-controlled one
    path = Path(".omh/state/ralph-state.json")
    raw = json.loads(path.read_text())
    assert raw["_meta"]["written_at"] != "2099-01-01T00:00:00+00:00"
    # And user data should not contain _meta
    assert "_meta" not in result["data"]


# ---------------------------------------------------------------------------
# New coverage tests
# ---------------------------------------------------------------------------

def test_schema_version_mismatch_warns(caplog):
    path = Path(".omh/state/ralph-state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"_meta": {"schema_version": 999, "written_at": "2099-01-01T00:00:00+00:00",
                               "mode": "ralph", "written_by": "omh-plugin"},
                    "active": True}),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="plugins.omh.omh_state"):
        result = state_read("ralph")
    assert result["exists"] is True
    assert any("schema_version" in record.message for record in caplog.records)


def test_large_state_warns(caplog):
    large_value = "x" * 200_000
    with caplog.at_level(logging.WARNING, logger="plugins.omh.omh_state"):
        result = state_write("ralph", {"active": True, "big": large_value})
    assert result["success"] is True
    assert any("large" in record.message for record in caplog.records)


def test_clear_unlink_error(monkeypatch):
    state_write("ralph", {"active": True})

    original_unlink = Path.unlink

    def fail_unlink(self, missing_ok=False):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    result = state_clear("ralph")
    monkeypatch.setattr(Path, "unlink", original_unlink)

    assert result["cleared"] is False
    assert "error" in result


def test_check_propagates_parse_error():
    path = Path(".omh/state/ralph-state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    result = state_check("ralph")
    assert "error" in result


def test_list_active_handles_glob_error(monkeypatch):
    import plugins.omh.omh_state as mod

    mock_dir = MagicMock()
    mock_dir.glob.side_effect = OSError("disk error")
    monkeypatch.setattr(mod, "_state_dir", lambda: mock_dir)
    mod._list_cache["result"] = None
    mod._list_cache["expires_at"] = 0.0

    result = state_list_active()
    assert result["modes"] == []


def test_check_cancel_on_nonexistent_file():
    result = state_check_cancel("nonexistent_mode")
    assert result["cancelled"] is False
    assert result["reason"] is None


def test_check_cancel_bad_timestamp():
    state_write("ralph", {
        "active": True,
        "cancel_requested": True,
        "cancel_at": "not-a-timestamp",
        "cancel_reason": "test",
    })
    result = state_check_cancel("ralph")
    # Bad timestamp means expiry check is skipped (except block passes) → signal treated as active
    assert result["cancelled"] is True


# ===========================================================================
# Per-instance state files (instance_id parameter)
# ===========================================================================

from plugins.omh.omh_state import (
    state_list_instances,
    state_lock_acquire,
    state_lock_check,
    state_lock_release,
    _slugify_instance,
)


def test_instance_id_writes_distinct_file():
    state_write("deep-research", {"active": True, "topic": "A"}, instance_id="topic-a")
    state_write("deep-research", {"active": True, "topic": "B"}, instance_id="topic-b")
    p_a = Path(".omh/state/deep-research--topic-a.json")
    p_b = Path(".omh/state/deep-research--topic-b.json")
    assert p_a.exists() and p_b.exists()


def test_instance_id_isolation():
    state_write("ralph", {"active": True, "phase": "X", "iteration": 1}, instance_id="plan-one")
    state_write("ralph", {"active": True, "phase": "Y", "iteration": 9}, instance_id="plan-two")
    a = state_read("ralph", instance_id="plan-one")
    b = state_read("ralph", instance_id="plan-two")
    assert a["data"]["phase"] == "X"
    assert b["data"]["phase"] == "Y"


def test_singleton_and_instance_coexist():
    state_write("ralph", {"active": True, "phase": "singleton"})
    state_write("ralph", {"active": True, "phase": "scoped"}, instance_id="myplan")
    assert Path(".omh/state/ralph-state.json").exists()
    assert Path(".omh/state/ralph--myplan.json").exists()
    assert state_read("ralph")["data"]["phase"] == "singleton"
    assert state_read("ralph", "myplan")["data"]["phase"] == "scoped"


def test_instance_id_slugification():
    state_write("ralph", {"active": True}, instance_id="My Plan / v2!!")
    expected = Path(".omh/state/ralph--my-plan-v2.json")
    assert expected.exists()


def test_instance_id_double_dash_separator_disambiguates_hyphenated_modes():
    """deep-research--myslug must parse as (deep-research, myslug), not (deep, research-myslug)."""
    state_write("deep-research", {"active": True, "phase": "search"}, instance_id="myslug")
    state_write("deep-interview", {"active": True, "phase": "ask"}, instance_id="myslug")
    listed = state_list_active()["modes"]
    by_mode = {(m["mode"], m.get("instance_id")) for m in listed}
    assert ("deep-research", "myslug") in by_mode
    assert ("deep-interview", "myslug") in by_mode


def test_list_active_includes_instances_with_singleton():
    state_write("ralph", {"active": True})
    state_write("ralph", {"active": True}, instance_id="alpha")
    state_write("ralph", {"active": True}, instance_id="beta")
    listed = state_list_active()["modes"]
    keys = {(m["mode"], m.get("instance_id")) for m in listed}
    assert ("ralph", None) in keys
    assert ("ralph", "alpha") in keys
    assert ("ralph", "beta") in keys


def test_list_instances_returns_all_for_one_mode():
    state_write("ralph", {"active": True})
    state_write("ralph", {"active": False}, instance_id="done")
    state_write("ralph", {"active": True}, instance_id="running")
    state_write("autopilot", {"active": True}, instance_id="ignored")
    result = state_list_instances("ralph")
    assert result["mode"] == "ralph"
    ids = {item["instance_id"] for item in result["instances"]}
    assert ids == {None, "done", "running"}


def test_clear_per_instance_does_not_affect_singleton():
    state_write("ralph", {"active": True, "phase": "keep"})
    state_write("ralph", {"active": True, "phase": "discard"}, instance_id="x")
    state_clear("ralph", instance_id="x")
    assert not Path(".omh/state/ralph--x.json").exists()
    assert Path(".omh/state/ralph-state.json").exists()
    assert state_read("ralph")["data"]["phase"] == "keep"


def test_cancel_per_instance():
    state_write("deep-research", {"active": True}, instance_id="topic-a")
    state_write("deep-research", {"active": True}, instance_id="topic-b")
    state_cancel("deep-research", reason="user said stop", instance_id="topic-a")
    a = state_check_cancel("deep-research", instance_id="topic-a")
    b = state_check_cancel("deep-research", instance_id="topic-b")
    assert a["cancelled"] is True
    assert b["cancelled"] is False


def test_slugify_rejects_empty_and_huge_inputs():
    with pytest.raises(ValueError):
        _slugify_instance("")
    with pytest.raises(ValueError):
        _slugify_instance("!!!")
    with pytest.raises(ValueError):
        _slugify_instance("x" * 1000)


# ===========================================================================
# Advisory locks
# ===========================================================================


def test_lock_acquire_then_release():
    r = state_lock_acquire("ralph", "plan-1", session_id="sess-A")
    assert r["acquired"] is True
    assert Path(r["path"]).exists()
    rel = state_lock_release("ralph", "plan-1", session_id="sess-A")
    assert rel["released"] is True
    assert not Path(r["path"]).exists()


def test_lock_blocks_second_acquirer():
    state_lock_acquire("ralph", "plan-X", session_id="sess-A")
    second = state_lock_acquire("ralph", "plan-X", session_id="sess-B")
    assert second["acquired"] is False
    assert second["held_by"]["session_id"] == "sess-A"


def test_lock_check_inspect_only():
    state_lock_acquire("ralph", "plan-Y", session_id="sess-A")
    info = state_lock_check("ralph", "plan-Y")
    assert info["held"] is True
    assert info["holder"]["session_id"] == "sess-A"
    # Check is non-mutating
    info2 = state_lock_check("ralph", "plan-Y")
    assert info2["held"] is True


def test_lock_release_session_mismatch_blocked():
    state_lock_acquire("ralph", "plan-Z", session_id="sess-A")
    rel = state_lock_release("ralph", "plan-Z", session_id="sess-other")
    assert rel["released"] is False


def test_lock_release_force_overrides():
    state_lock_acquire("ralph", "plan-W", session_id="sess-A")
    rel = state_lock_release("ralph", "plan-W", session_id="sess-other", force=True)
    assert rel["released"] is True


def test_lock_stale_pid_auto_released(monkeypatch):
    import plugins.omh.omh_state as mod
    # Acquire as a fake dead pid
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(mod.os, "getpid", lambda: 999999)
    state_lock_acquire("ralph", "plan-stale", session_id="sess-old")
    # Now pretend a new process tries to acquire — pid_alive still false → stale, replaced
    monkeypatch.setattr(mod.os, "getpid", lambda: 123)
    r = state_lock_acquire("ralph", "plan-stale", session_id="sess-new")
    assert r["acquired"] is True
    assert r["holder"]["session_id"] == "sess-new"


def test_lock_release_when_missing_is_idempotent():
    rel = state_lock_release("ralph", "never-locked", session_id="sess-A")
    assert rel["released"] is True
    assert rel["existed"] is False


# ===========================================================================
# Tool dispatch — per-instance and lock actions
# ===========================================================================


def test_handler_write_with_instance_id():
    out = json.loads(omh_state_handler({
        "action": "write", "mode": "deep-research",
        "instance_id": "abc", "data": {"active": True, "topic": "T"},
    }))
    assert out["success"] is True
    assert Path(".omh/state/deep-research--abc.json").exists()


def test_handler_lock_unlock_roundtrip():
    acq = json.loads(omh_state_handler({
        "action": "lock", "mode": "ralph",
        "lock_key": "plan-tool", "session_id": "tool-sess",
    }))
    assert acq["acquired"] is True
    contend = json.loads(omh_state_handler({
        "action": "lock", "mode": "ralph",
        "lock_key": "plan-tool", "session_id": "other-sess",
    }))
    assert contend["acquired"] is False
    assert contend["held_by"]["session_id"] == "tool-sess"
    rel = json.loads(omh_state_handler({
        "action": "unlock", "mode": "ralph",
        "lock_key": "plan-tool", "session_id": "tool-sess",
    }))
    assert rel["released"] is True


def test_handler_lock_check_does_not_mutate():
    omh_state_handler({
        "action": "lock", "mode": "ralph",
        "lock_key": "plan-tc", "session_id": "tc-sess",
    })
    out1 = json.loads(omh_state_handler({
        "action": "lock_check", "mode": "ralph", "lock_key": "plan-tc",
    }))
    out2 = json.loads(omh_state_handler({
        "action": "lock_check", "mode": "ralph", "lock_key": "plan-tc",
    }))
    assert out1["held"] is True and out2["held"] is True


def test_handler_lock_requires_lock_key():
    out = json.loads(omh_state_handler({"action": "lock", "mode": "ralph"}))
    assert "error" in out


def test_handler_list_instances():
    omh_state_handler({"action": "write", "mode": "ralph",
                       "instance_id": "p1", "data": {"active": True}})
    omh_state_handler({"action": "write", "mode": "ralph",
                       "instance_id": "p2", "data": {"active": True}})
    out = json.loads(omh_state_handler({"action": "list_instances", "mode": "ralph"}))
    ids = {i["instance_id"] for i in out["instances"]}
    assert ids == {"p1", "p2"}
