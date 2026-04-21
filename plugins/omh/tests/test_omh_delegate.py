"""Tests for omh_delegate.py — v0 hardened wrapper.

Per .omh/research/ralplan-omh-delegate/round2-planner.md §3 test list:
  1. Happy path (M6 — first test)
  2. Contract violation
  3. delegate_task raises
  4. (optional) Path-discovery walk-up
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugins.omh.omh_delegate import (
    omh_delegate,
    omh_delegate_prepare,
    omh_delegate_finalize,
    _discover_project_root,
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Create a project-root with a .omh/ marker; chdir into it."""
    (tmp_path / ".omh").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: happy path (M6 — first test in the file)
# ---------------------------------------------------------------------------


def test_happy_path_subagent_obeys_contract(project):
    """Subagent obeys the contract: writes file at expected path, returns the path string."""
    captured = {}

    def fake_delegate(*, goal, context="", **kwargs):
        # Extract expected path from the injected contract block.
        marker = "<<<EXPECTED_OUTPUT_PATH>>>"
        end = "<<<END_EXPECTED_OUTPUT_PATH>>>"
        path_str = goal.split(marker, 1)[1].split(end, 1)[0].strip()
        Path(path_str).write_text("# subagent artifact\n\nhello\n", encoding="utf-8")
        captured["goal"] = goal
        captured["path"] = path_str
        return path_str  # subagent's return value

    result = omh_delegate(
        role="planner",
        goal="Plan something useful.",
        mode="ralplan",
        phase="round1-planner",
        round=1,
        delegate_fn=fake_delegate,
    )

    assert result["ok"] is True
    assert result["ok_strict"] is True  # AC-1
    assert result["file_present"] is True
    assert result["contract_satisfied"] is True
    assert result["recovered_by_wrapper"] is False

    # Artifact landed at the expected path
    artifact = Path(result["path"])
    assert artifact.is_file()
    assert artifact.read_text(encoding="utf-8").startswith("# subagent artifact")

    # Both breadcrumbs present
    bdir = project / ".omh" / "state" / "dispatched"
    assert bdir.is_dir()
    dispatched = list(bdir.glob("*.dispatched.json"))
    completed = list(bdir.glob("*.completed.json"))
    assert len(dispatched) == 1
    assert len(completed) == 1

    # Dispatched breadcrumb shape
    d = json.loads(dispatched[0].read_text())
    assert d["mode"] == "ralplan"
    assert d["phase"] == "round1-planner"
    assert d["round"] == 1
    assert d["role"] == "planner"
    assert d["expected_output_path"] == result["path"]
    assert d["goal_sha256"] and len(d["goal_sha256"]) == 64
    assert d["goal_bytes"] == len(b"Plan something useful.")
    assert "goal_preview" not in d  # W2: no preview, only hash + length
    assert "goal" not in d           # W2: raw goal must not leak

    # Completion breadcrumb shape
    c = json.loads(completed[0].read_text())
    assert c["file_present"] is True
    assert c["contract_satisfied"] is True
    assert c["recovered_by_wrapper"] is False
    assert c["bytes"] > 0
    assert c["raw_return_kind"] == "string"
    assert c["error"] is None


# ---------------------------------------------------------------------------
# Test 2: contract violation — subagent returns prose, no file written
# ---------------------------------------------------------------------------


def test_contract_violation_no_rescue(project, capsys):
    """Subagent ignores contract: returns prose, writes no file. v0 has no rescue."""

    def fake_delegate(*, goal, context="", **kwargs):
        return "Sure! Here's what I'd write:\n\n# Plan\n\nstep 1: do thing"

    result = omh_delegate(
        role="planner",
        goal="Plan something.",
        mode="ralplan",
        phase="round1-planner",
        delegate_fn=fake_delegate,
    )

    assert result["ok"] is False
    assert result["ok_strict"] is False  # AC-1
    assert result["file_present"] is False
    assert result["contract_satisfied"] is False
    assert result["recovered_by_wrapper"] is False

    # No rescue artifact at expected path
    assert not Path(result["path"]).exists()

    # Raw return preserved on completion breadcrumb
    bdir = project / ".omh" / "state" / "dispatched"
    completed = json.loads(next(bdir.glob("*.completed.json")).read_text())
    assert completed["file_present"] is False
    assert completed["contract_satisfied"] is False
    assert "Here's what I'd write" in completed["raw_return"]
    assert completed["raw_return_kind"] == "string"
    assert completed["error"] is None  # No exception, just contract violation

    # W5: stderr warning fires
    captured = capsys.readouterr()
    assert "omh_delegate[contract_violation]" in captured.err
    assert result["id"] in captured.err


# ---------------------------------------------------------------------------
# Test 3: delegate_task raises — breadcrumb captures error, exception re-raised
# ---------------------------------------------------------------------------


def test_delegate_task_raises(project, capsys):
    """delegate_task itself raises an exception."""

    def fake_delegate(*, goal, context="", **kwargs):
        raise RuntimeError("simulated dispatch failure")

    with pytest.raises(RuntimeError, match="simulated dispatch failure"):
        omh_delegate(
            role="planner",
            goal="Plan.",
            mode="ralplan",
            phase="round1-planner",
            delegate_fn=fake_delegate,
        )

    # Both breadcrumbs landed even though we raised
    bdir = project / ".omh" / "state" / "dispatched"
    dispatched = list(bdir.glob("*.dispatched.json"))
    completed = list(bdir.glob("*.completed.json"))
    assert len(dispatched) == 1
    assert len(completed) == 1

    c = json.loads(completed[0].read_text())
    assert c["file_present"] is False
    assert c["contract_satisfied"] is False
    assert c["error"] is not None
    assert "RuntimeError" in c["error"]
    assert "simulated dispatch failure" in c["error"]

    # W5: stderr warning fires for exception too
    captured = capsys.readouterr()
    assert "omh_delegate[exception]" in captured.err


# ---------------------------------------------------------------------------
# Test 4: project-root walk-up discovery (W4)
# ---------------------------------------------------------------------------


def test_project_root_discovered_from_nested_subdir(tmp_path, monkeypatch):
    """When invoked from a subdirectory of the project, discover the .omh/ root."""
    (tmp_path / ".omh").mkdir()
    nested = tmp_path / "deeply" / "nested" / "subdir"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    # Direct discovery test
    found = _discover_project_root()
    assert found == tmp_path.resolve()

    # End-to-end: artifact lands under the discovered root, not under cwd
    def fake_delegate(*, goal, context="", **kwargs):
        marker = "<<<EXPECTED_OUTPUT_PATH>>>"
        end = "<<<END_EXPECTED_OUTPUT_PATH>>>"
        path_str = goal.split(marker, 1)[1].split(end, 1)[0].strip()
        Path(path_str).write_text("ok", encoding="utf-8")
        return path_str

    result = omh_delegate(
        role="planner",
        goal="Plan.",
        mode="ralplan",
        phase="round1-planner",
        delegate_fn=fake_delegate,
    )

    assert result["ok"] is True
    artifact_path = Path(result["path"])
    # Artifact is under tmp_path/.omh/research, NOT under nested/.omh/research
    assert tmp_path.resolve() in artifact_path.parents
    assert nested not in artifact_path.parents


def test_project_root_falls_back_to_cwd_when_no_marker(tmp_path, monkeypatch):
    """No .omh/ found anywhere upward: fall back to cwd."""
    monkeypatch.chdir(tmp_path)
    # Ensure no .omh/ in tmp_path or any ancestor we control
    assert not (tmp_path / ".omh").exists()
    found = _discover_project_root()
    assert found == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Test 5: schema stability — three-boolean status always present (Architect C5)
# ---------------------------------------------------------------------------


def test_three_boolean_status_always_present(project):
    """C5: file_present, contract_satisfied, recovered_by_wrapper always in result."""

    def fake_delegate(*, goal, context="", **kwargs):
        marker = "<<<EXPECTED_OUTPUT_PATH>>>"
        end = "<<<END_EXPECTED_OUTPUT_PATH>>>"
        path_str = goal.split(marker, 1)[1].split(end, 1)[0].strip()
        Path(path_str).write_text("x", encoding="utf-8")
        return path_str

    result = omh_delegate(
        role="planner", goal="g", mode="ralplan", phase="p",
        delegate_fn=fake_delegate,
    )
    for key in ("file_present", "contract_satisfied", "recovered_by_wrapper",
                "ok", "ok_strict", "path", "id", "raw"):
        assert key in result, f"missing required key: {key}"


# ---------------------------------------------------------------------------
# Test 6: append-only breadcrumbs (Architect C1) — completion is a SEPARATE file
# ---------------------------------------------------------------------------


def test_breadcrumbs_are_append_only_separate_files(project):
    """C1: dispatched.json and completed.json are distinct files; no RMW."""

    def fake_delegate(*, goal, context="", **kwargs):
        marker = "<<<EXPECTED_OUTPUT_PATH>>>"
        end = "<<<END_EXPECTED_OUTPUT_PATH>>>"
        path_str = goal.split(marker, 1)[1].split(end, 1)[0].strip()
        Path(path_str).write_text("x", encoding="utf-8")
        return path_str

    result = omh_delegate(
        role="planner", goal="g", mode="ralplan", phase="p",
        delegate_fn=fake_delegate,
    )

    bdir = project / ".omh" / "state" / "dispatched"
    files = sorted(p.name for p in bdir.iterdir())
    assert len(files) == 2
    assert any(f.endswith(".dispatched.json") for f in files)
    assert any(f.endswith(".completed.json") for f in files)

    # The dispatch breadcrumb must NOT have been mutated to add completion fields
    d = json.loads((bdir / f"{result['id']}.dispatched.json").read_text())
    assert "completed_at" not in d
    assert "file_present" not in d
    assert d["_meta"]["kind"] == "dispatch"


# ---------------------------------------------------------------------------
# Test 7: prepare/finalize split — primary API for agent loops (Bug D1 fix)
# ---------------------------------------------------------------------------


def test_prepare_returns_augmented_goal_and_writes_dispatched_breadcrumb(project):
    """prepare() must inject the contract, write the dispatched breadcrumb,
    and return everything the agent needs to perform the dispatch itself."""
    prep = omh_delegate_prepare(
        role="planner", goal="Plan stuff.", mode="ralplan",
        phase="round1-planner", round=1, context="ctx-data",
    )

    # Required keys for the agent to dispatch
    for key in ("id", "expected_path", "augmented_goal", "context",
                "breadcrumb_dir", "project_root", "mode", "phase",
                "round", "slug", "role"):
        assert key in prep, f"missing prepare() result key: {key}"

    # Contract block was injected
    assert "<<<EXPECTED_OUTPUT_PATH>>>" in prep["augmented_goal"]
    assert prep["expected_path"] in prep["augmented_goal"]
    assert prep["augmented_goal"].startswith("Plan stuff.")  # original preserved

    # Dispatched breadcrumb written; no completion yet
    bdir = project / ".omh" / "state" / "dispatched"
    dispatched = list(bdir.glob("*.dispatched.json"))
    completed = list(bdir.glob("*.completed.json"))
    assert len(dispatched) == 1
    assert len(completed) == 0  # finalize hasn't been called yet

    d = json.loads(dispatched[0].read_text())
    assert d["id"] == prep["id"]
    assert d["context_bytes"] == len(b"ctx-data")


def test_finalize_happy_path(project):
    """finalize() with file present + raw_return matching path = ok=True."""
    prep = omh_delegate_prepare(
        role="planner", goal="g", mode="ralplan", phase="p",
    )
    # Simulate the subagent obeying the contract
    Path(prep["expected_path"]).write_text("# artifact\n", encoding="utf-8")

    res = omh_delegate_finalize(prep=prep, raw_return=prep["expected_path"])
    assert res["ok"] is True
    assert res["ok_strict"] is True
    assert res["file_present"] is True
    assert res["contract_satisfied"] is True
    assert res["recovered_by_wrapper"] is False
    assert res["path"] == prep["expected_path"]
    assert res["id"] == prep["id"]


def test_finalize_contract_violation_no_file(project, capsys):
    """finalize() with no file present = ok=False + stderr warning."""
    prep = omh_delegate_prepare(
        role="planner", goal="g", mode="ralplan", phase="p",
    )
    # Subagent ignored contract — no file written
    res = omh_delegate_finalize(
        prep=prep,
        raw_return="Sure, here's some prose instead of a path.",
    )
    assert res["ok"] is False
    assert res["ok_strict"] is False
    assert res["file_present"] is False
    assert res["contract_satisfied"] is False

    captured = capsys.readouterr()
    assert "omh_delegate[contract_violation]" in captured.err


def test_finalize_with_error_propagates_to_breadcrumb(project, capsys):
    """When the agent's dispatch raised, pass error= and finalize records it
    on the completion breadcrumb (does NOT re-raise — agent owns that)."""
    prep = omh_delegate_prepare(
        role="planner", goal="g", mode="ralplan", phase="p",
    )
    res = omh_delegate_finalize(
        prep=prep,
        raw_return=None,
        error="RuntimeError: simulated dispatch failure",
    )
    assert res["ok"] is False
    assert res["file_present"] is False

    bdir = project / ".omh" / "state" / "dispatched"
    completed = json.loads(next(bdir.glob("*.completed.json")).read_text())
    assert completed["error"] == "RuntimeError: simulated dispatch failure"

    captured = capsys.readouterr()
    assert "omh_delegate[exception]" in captured.err


def test_omh_delegate_requires_explicit_delegate_fn():
    """The convenience orchestrator must reject delegate_fn=None loudly,
    NOT fall through to a broken default import (Bug D1 regression guard)."""
    with pytest.raises(TypeError, match="explicit delegate_fn"):
        omh_delegate(
            role="planner", goal="g", mode="ralplan", phase="p",
            delegate_fn=None,
        )


def test_omh_delegate_orchestrator_calls_prepare_and_finalize(project):
    """The convenience orchestrator must produce the same end-state as
    explicit prepare/finalize: one dispatched + one completed breadcrumb,
    artifact at the expected path, structured result returned."""
    def fake_delegate(*, goal, context="", **kwargs):
        marker = "<<<EXPECTED_OUTPUT_PATH>>>"
        end = "<<<END_EXPECTED_OUTPUT_PATH>>>"
        path_str = goal.split(marker, 1)[1].split(end, 1)[0].strip()
        Path(path_str).write_text("orch", encoding="utf-8")
        return path_str

    res = omh_delegate(
        role="planner", goal="g", mode="ralplan", phase="p",
        delegate_fn=fake_delegate,
    )
    assert res["ok"] is True

    bdir = project / ".omh" / "state" / "dispatched"
    assert len(list(bdir.glob("*.dispatched.json"))) == 1
    assert len(list(bdir.glob("*.completed.json"))) == 1
