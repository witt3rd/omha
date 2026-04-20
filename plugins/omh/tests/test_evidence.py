"""Tests for evidence_tool.py — omh_gather_evidence."""

import json
import sys

import pytest

import plugins.omh.omh_config as omh_config_module
from plugins.omh.tools.evidence_tool import omh_evidence_handler


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    omh_config_module._config_cache = {
        "evidence": {
            "allowlist_prefixes": ["echo ", "python -m pytest", "true", "false"],
            "max_commands": 5,
            "default_timeout": 10,
            "default_truncate": 500,
        }
    }
    yield
    omh_config_module._config_cache = None


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------

def test_allowed_command_passes():
    result = json.loads(omh_evidence_handler({"commands": ["echo hello"]}))
    assert "error" not in result
    assert result["all_pass"] is True


def test_rejected_command_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["rm -rf /"]}))
    assert result["all_pass"] is False
    assert len(result["results"]) == 1
    assert result["results"][0]["passed"] is False
    assert "not in allowlist" in result["results"][0]["output"]


def test_mixed_allowlist_blocks_all():
    # With per-command rejection, "echo hi" should succeed and "curl evil.com" should fail
    result = json.loads(omh_evidence_handler({"commands": ["echo hi", "curl evil.com"]}))
    assert result["all_pass"] is False
    assert len(result["results"]) == 2
    assert result["results"][0]["passed"] is True  # echo hi succeeds
    assert result["results"][1]["passed"] is False  # curl evil.com fails allowlist
    assert "not in allowlist" in result["results"][1]["output"]


# ---------------------------------------------------------------------------
# Multi-command results
# ---------------------------------------------------------------------------

def test_multiple_commands():
    result = json.loads(omh_evidence_handler({"commands": ["echo a", "echo b"]}))
    assert len(result["results"]) == 2
    assert result["summary"] == "2/2 passed"


def test_failed_command_captured():
    result = json.loads(omh_evidence_handler({"commands": ["false"]}))
    assert result["all_pass"] is False
    assert result["results"][0]["exit_code"] != 0
    assert result["summary"] == "0/1 passed"


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def test_output_truncated():
    result = json.loads(omh_evidence_handler({"commands": ["echo hello"], "truncate": 2}))
    output = result["results"][0]["output"]
    assert len(output) <= 2


def test_tail_preserved():
    # echo produces "hello\n" — with truncate=3 we should get the tail "\n" or "lo\n"
    result = json.loads(omh_evidence_handler({"commands": ["echo hello"], "truncate": 4}))
    output = result["results"][0]["output"]
    assert output == "llo\n" or output.endswith("\n")


# ---------------------------------------------------------------------------
# Max command count
# ---------------------------------------------------------------------------

def test_max_commands_enforced():
    cmds = ["echo x"] * 6  # max is 5
    result = json.loads(omh_evidence_handler({"commands": cmds}))
    assert "error" in result
    assert "Too many" in result["error"]


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

def test_timeout_kills_command():
    # sleep 5 with timeout=0 should timeout immediately
    omh_config_module._config_cache["evidence"]["allowlist_prefixes"].append("sleep ")
    result = json.loads(omh_evidence_handler({"commands": ["sleep 5"], "timeout": 0}))
    r = result["results"][0]
    assert r["passed"] is False
    assert "TIMEOUT" in r["output"]


# ---------------------------------------------------------------------------
# Empty commands
# ---------------------------------------------------------------------------

def test_empty_commands_error():
    result = json.loads(omh_evidence_handler({"commands": []}))
    assert "error" in result


# ---------------------------------------------------------------------------
# Shell metacharacter / injection prevention
# ---------------------------------------------------------------------------

def test_semicolon_injection_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["echo hi; rm -rf /"]}))
    assert "error" in result
    assert "echo hi; rm -rf /" in result["rejected"]


def test_newline_injection_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["echo hi\nrm -rf /"]}))
    assert "error" in result
    assert "echo hi\nrm -rf /" in result["rejected"]


def test_pipe_injection_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["echo hi | cat /etc/passwd"]}))
    assert "error" in result


def test_partial_word_prefix_blocked():
    # Token-level check: "pytestmalicious" != "pytest" so this must be rejected.
    result = json.loads(omh_evidence_handler({"commands": ["python -m pytestmalicious"]}))
    assert result["all_pass"] is False
    assert len(result["results"]) == 1
    assert result["results"][0]["passed"] is False
    assert "not in allowlist" in result["results"][0]["output"]


def test_clean_command_not_blocked_by_metachar_check():
    result = json.loads(omh_evidence_handler({"commands": ["echo hello world"]}))
    assert "error" not in result
    assert result["all_pass"] is True


# ---------------------------------------------------------------------------
# workdir parameter
# ---------------------------------------------------------------------------

def test_workdir_within_project_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subdir = tmp_path / "sub"
    subdir.mkdir()
    result = json.loads(omh_evidence_handler({"commands": ["echo hi"], "workdir": str(subdir)}))
    assert result["all_pass"] is True


def test_workdir_outside_project_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = json.loads(omh_evidence_handler({"commands": ["echo hi"], "workdir": "/tmp"}))
    assert "error" in result
    assert "workdir" in result["error"]


# ---------------------------------------------------------------------------
# Additional metacharacter injection variants
# ---------------------------------------------------------------------------

def test_double_ampersand_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["echo a && rm -rf /"]}))
    assert "error" in result


def test_double_pipe_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["echo a || evil"]}))
    assert "error" in result


def test_backtick_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["echo `id`"]}))
    assert "error" in result


def test_dollar_paren_blocked():
    result = json.loads(omh_evidence_handler({"commands": ["echo $(id)"]}))
    assert "error" in result


# ---------------------------------------------------------------------------
# Hard caps on timeout and truncate
# ---------------------------------------------------------------------------

def test_timeout_capped_at_max():
    # We can't easily test timeout enforcement without a slow command,
    # but we can verify the handler doesn't error on very large timeout input
    omh_config_module._config_cache["evidence"]["allowlist_prefixes"].append("true")
    result = json.loads(omh_evidence_handler({"commands": ["true"], "timeout": 999999}))
    assert "error" not in result


def test_truncate_capped_at_max():
    result = json.loads(omh_evidence_handler({"commands": ["echo hi"], "truncate": 999999999}))
    assert "error" not in result
    # Output should be present (not truncated to absurdly small value)
    assert result["results"][0]["output"]


# ---------------------------------------------------------------------------
# FileNotFoundError handling
# ---------------------------------------------------------------------------

def test_file_not_found_error():
    # Add a nonexistent command to allowlist, then verify proper error handling
    omh_config_module._config_cache["evidence"]["allowlist_prefixes"].append("nonexistent-cmd")
    result = json.loads(omh_evidence_handler({"commands": ["nonexistent-cmd --version"]}))
    assert result["all_pass"] is False
    assert len(result["results"]) == 1
    r = result["results"][0]
    assert r["passed"] is False
    assert "Command not found" in r["output"]
    assert "nonexistent-cmd" in r["output"]


# ---------------------------------------------------------------------------
# Empty prefix in allowlist is skipped (line 38)
# ---------------------------------------------------------------------------

def test_empty_prefix_in_allowlist_is_skipped(monkeypatch):
    omh_config_module._config_cache["evidence"]["allowlist_prefixes"] = ["", "python3 -m pytest"]
    result = json.loads(omh_evidence_handler({"commands": ["python3 -m pytest ."]}))
    # The empty prefix must not cause a match by itself; the real prefix should match
    assert "error" not in result
    assert len(result["results"]) == 1
    assert result["results"][0]["passed"] is not None  # command was allowed (not rejected by allowlist)
    assert "not in allowlist" not in result["results"][0].get("output", "")


# ---------------------------------------------------------------------------
# shlex.split parse failure (lines 129-130)
# ---------------------------------------------------------------------------

def test_command_parse_error_returns_error():
    result = json.loads(omh_evidence_handler({"commands": ["python3 -m pytest 'unclosed"]}))
    assert "error" in result
    assert "rejected" in result
    assert "python3 -m pytest 'unclosed" in result["rejected"]


# ---------------------------------------------------------------------------
# Generic exception during subprocess execution (lines 187-188)
# ---------------------------------------------------------------------------

def test_command_generic_exception(monkeypatch):
    omh_config_module._config_cache["evidence"]["allowlist_prefixes"].append("python3 -m pytest")
    monkeypatch.setattr("plugins.omh.tools.evidence_tool.subprocess.run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("unexpected")))
    result = json.loads(omh_evidence_handler({"commands": ["python3 -m pytest ."]}))
    r = result["results"][0]
    assert r["exit_code"] == -1
    assert "ERROR" in r["output"]


# ---------------------------------------------------------------------------
# project_root config key (#16)
# ---------------------------------------------------------------------------

def test_project_root_config_allows_subdir(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subdir = root / "src"
    subdir.mkdir()
    omh_config_module._config_cache["project_root"] = str(root)
    result = json.loads(omh_evidence_handler({"commands": ["echo hi"], "workdir": str(subdir)}))
    assert result["all_pass"] is True


def test_project_root_config_rejects_outside(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    omh_config_module._config_cache["project_root"] = str(root)
    result = json.loads(omh_evidence_handler({"commands": ["echo hi"], "workdir": str(outside)}))
    assert "error" in result
    assert "workdir" in result["error"]
