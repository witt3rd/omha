"""Tests for omh_roles: role catalog, marker extraction, prompt loading."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

import plugins.omh.omh_config as omh_config_module
from ..omh_roles import extract_role_marker, get_role_catalog, load_role_prompt, is_debug, debug_print


# ---------------------------------------------------------------------------
# extract_role_marker
# ---------------------------------------------------------------------------

def test_extract_role_marker_valid():
    assert extract_role_marker("[omh-role:executor]") == "executor"


def test_extract_role_marker_with_surrounding_text():
    assert extract_role_marker("[omh-role:verifier] Implement this task") == "verifier"


def test_extract_role_marker_mid_sentence():
    assert extract_role_marker("goal: [omh-role:architect] review the plan") == "architect"


def test_extract_role_marker_none():
    assert extract_role_marker("no marker here") is None


def test_extract_role_marker_empty():
    assert extract_role_marker("") is None


def test_extract_role_marker_path_traversal_rejected():
    # Regex only matches [a-zA-Z0-9_-]+ so path traversal is not captured
    assert extract_role_marker("[omh-role:../../etc/passwd]") is None


def test_extract_role_marker_spaces_rejected():
    assert extract_role_marker("[omh-role:exec utor]") is None


def test_extract_role_marker_returns_first_when_multiple():
    result = extract_role_marker("[omh-role:executor] foo [omh-role:verifier]")
    assert result == "executor"


# ---------------------------------------------------------------------------
# get_role_catalog
# ---------------------------------------------------------------------------

def test_get_role_catalog_returns_all_roles():
    catalog = get_role_catalog()
    expected = {
        "analyst", "architect", "code-reviewer", "critic", "debugger",
        "executor", "planner", "security-reviewer", "test-engineer", "verifier",
    }
    assert expected == set(catalog.keys())


def test_get_role_catalog_values_are_paths():
    catalog = get_role_catalog()
    for name, path in catalog.items():
        assert isinstance(path, Path), f"{name} should map to a Path"
        assert path.exists(), f"Role file missing: {path}"


def test_get_role_catalog_missing_dir_returns_empty(tmp_path):
    with patch("plugins.omh.omh_roles._REFERENCES_DIR", tmp_path / "nonexistent"):
        catalog = get_role_catalog()
    assert catalog == {}


# ---------------------------------------------------------------------------
# load_role_prompt
# ---------------------------------------------------------------------------

def test_load_role_prompt_valid():
    prompt = load_role_prompt("executor")
    assert prompt is not None
    assert len(prompt) > 10


def test_load_role_prompt_unknown_returns_none():
    assert load_role_prompt("nonexistent-role") is None


def test_load_role_prompt_path_traversal_returns_none():
    assert load_role_prompt("../../etc/passwd") is None


def test_load_role_prompt_empty_string_returns_none():
    assert load_role_prompt("") is None


def test_load_role_prompt_all_catalog_roles():
    """Every role in the catalog must load successfully."""
    catalog = get_role_catalog()
    for role in catalog:
        prompt = load_role_prompt(role)
        assert prompt is not None, f"load_role_prompt('{role}') returned None"
        assert len(prompt) > 0, f"load_role_prompt('{role}') returned empty string"


def test_load_role_prompt_reads_fresh(tmp_path):
    """Role files are read from disk each time (no stale caching)."""
    role_file = tmp_path / "role-testrole.md"
    role_file.write_text("version 1")
    with patch("plugins.omh.omh_roles._REFERENCES_DIR", tmp_path):
        first = load_role_prompt("testrole")
        role_file.write_text("version 2")
        second = load_role_prompt("testrole")
    assert first == "version 1"
    assert second == "version 2"


# ---------------------------------------------------------------------------
# load_role action via omh_state_handler
# ---------------------------------------------------------------------------

def test_handler_load_role_known(monkeypatch, tmp_path):
    role_file = tmp_path / "role-executor.md"
    role_file.write_text("You are an executor.")
    monkeypatch.setattr("plugins.omh.omh_roles._REFERENCES_DIR", tmp_path)

    from ..tools.state_tool import omh_state_handler
    result = json.loads(omh_state_handler({"action": "load_role", "role": "executor"}))
    assert result["role"] == "executor"
    assert result["prompt"] == "You are an executor."


def test_handler_load_role_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr("plugins.omh.omh_roles._REFERENCES_DIR", tmp_path)

    from ..tools.state_tool import omh_state_handler
    result = json.loads(omh_state_handler({"action": "load_role", "role": "ghost"}))
    assert "error" in result
    assert "ghost" in result["error"]


def test_handler_load_role_missing_param():
    from ..tools.state_tool import omh_state_handler
    result = json.loads(omh_state_handler({"action": "load_role"}))
    assert "error" in result
    assert "role parameter" in result["error"]


def test_handler_load_role_path_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr("plugins.omh.omh_roles._REFERENCES_DIR", tmp_path)

    from ..tools.state_tool import omh_state_handler
    result = json.loads(omh_state_handler({"action": "load_role", "role": "../../etc/passwd"}))
    assert "error" in result


# ---------------------------------------------------------------------------
# is_debug() via environment variable (lines 27-28)
# ---------------------------------------------------------------------------

def test_is_debug_env_var_true(monkeypatch):
    monkeypatch.setenv("OMH_DEBUG", "1")
    assert is_debug() is True


def test_is_debug_env_var_true_word(monkeypatch):
    monkeypatch.setenv("OMH_DEBUG", "true")
    assert is_debug() is True


# ---------------------------------------------------------------------------
# is_debug() reads from config (lines 32-33)
# ---------------------------------------------------------------------------

def test_is_debug_from_config(monkeypatch):
    monkeypatch.delenv("OMH_DEBUG", raising=False)
    monkeypatch.setattr(omh_config_module, "_config_cache", {"debug": True})
    assert is_debug() is True


# ---------------------------------------------------------------------------
# debug_print outputs when enabled (lines 38-39)
# ---------------------------------------------------------------------------

def test_debug_print_outputs_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv("OMH_DEBUG", "1")
    debug_print("hello test")
    captured = capsys.readouterr()
    assert "[OMH DEBUG]" in captured.out
    assert "hello test" in captured.out


# ---------------------------------------------------------------------------
# get_role_catalog() when references dir doesn't exist (line 47)
# ---------------------------------------------------------------------------

def test_get_role_catalog_missing_dir(monkeypatch):
    monkeypatch.setattr("plugins.omh.omh_roles._REFERENCES_DIR", Path("/nonexistent/path/xyz123"))
    assert get_role_catalog() == {}
