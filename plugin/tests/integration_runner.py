"""Standalone integration test runner — no pytest dependency.

Validates the OMH plugin loads correctly through the actual Hermes PluginManager.
Run with the Hermes venv:
    PYTHONPATH="$PWD" ~/.hermes/hermes-agent/venv/bin/python3 plugin/tests/integration_runner.py
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

# Add Hermes source to sys.path
HERMES_AGENT_DIR = Path.home() / ".hermes" / "hermes-agent"
if str(HERMES_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT_DIR))

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PASSED = 0
FAILED = 0
ERRORS = []


def test(name):
    """Decorator that runs a test function and tracks pass/fail."""
    def decorator(fn):
        global PASSED, FAILED
        try:
            fn()
            PASSED += 1
            print(f"  PASS  {name}")
        except Exception as e:
            FAILED += 1
            ERRORS.append((name, e))
            print(f"  FAIL  {name}")
            traceback.print_exc(limit=3)
            print()
        return fn
    return decorator


def setup_workdir():
    """Change to a temp directory and patch config for all loaded modules."""
    tmpdir = tempfile.mkdtemp(prefix="omh-integ-")
    os.chdir(tmpdir)
    config = {
        "state_dir": ".omh/state",
        "staleness_hours": 2,
        "cancel_ttl_seconds": 30,
        "evidence": {
            "allowlist_prefixes": ["echo", "true", "false"],
            "max_commands": 5,
            "default_timeout": 10,
            "default_truncate": 500,
        },
    }
    for key, mod in sys.modules.items():
        if key.endswith("omh_config") and hasattr(mod, "_config_cache"):
            mod._config_cache = dict(config)
    for key, mod in sys.modules.items():
        if key.endswith("omh_state") and hasattr(mod, "_list_cache"):
            mod._list_cache["result"] = None
            mod._list_cache["expires_at"] = 0.0
    return tmpdir


def load_plugin():
    """Load the OMH plugin through the Hermes PluginManager."""
    from hermes_cli.plugins import PluginManager, PluginManifest
    manager = PluginManager()
    manifest = PluginManifest(
        name="omh",
        version="0.1.0",
        source="project",
        path=str(PLUGIN_DIR),
    )
    manager._load_plugin(manifest)
    return manager


# ---- Tests ----------------------------------------------------------------

print(f"\nOMH Plugin Integration Tests (Hermes venv: {sys.executable})")
print(f"Plugin: {PLUGIN_DIR}")
print(f"Python: {sys.version}")
print("-" * 60)

manager = load_plugin()
tmpdir = setup_workdir()


@test("Plugin loads without errors")
def _():
    loaded = manager._plugins.get("omh")
    assert loaded is not None, "Plugin not found"
    assert loaded.enabled is True, f"Plugin disabled: {loaded.error}"
    assert loaded.error is None, f"Plugin error: {loaded.error}"


@test("Tools registered: omh_state, omh_gather_evidence")
def _():
    assert "omh_state" in manager._plugin_tool_names
    assert "omh_gather_evidence" in manager._plugin_tool_names


@test("Tools have correct toolset='omh' in registry")
def _():
    from tools.registry import registry
    for name in ["omh_state", "omh_gather_evidence"]:
        entry = registry._tools.get(name)
        assert entry is not None, f"{name} not in registry"
        assert entry.toolset == "omh", f"{name} toolset={entry.toolset}"
        assert callable(entry.handler), f"{name} handler not callable"
        assert isinstance(entry.schema, dict), f"{name} schema not dict"


@test("Hooks registered: pre_llm_call, on_session_end")
def _():
    assert "pre_llm_call" in manager._hooks
    assert len(manager._hooks["pre_llm_call"]) >= 1
    assert "on_session_end" in manager._hooks
    assert len(manager._hooks["on_session_end"]) >= 1


@test("omh_state tool: write → read → list → check → cancel → clear")
def _():
    from tools.registry import registry
    h = registry._tools["omh_state"].handler

    r = json.loads(h({"action": "write", "mode": "integ-test", "data": {"active": True, "phase": "testing"}}))
    assert r["success"] is True, f"write failed: {r}"

    r = json.loads(h({"action": "read", "mode": "integ-test"}))
    assert r["exists"] is True
    assert r["data"]["phase"] == "testing"

    # Reset list cache before listing
    for key, mod in sys.modules.items():
        if key.endswith("omh_state") and hasattr(mod, "_list_cache"):
            mod._list_cache["expires_at"] = 0.0

    r = json.loads(h({"action": "list"}))
    assert any(m["mode"] == "integ-test" for m in r["modes"]), f"integ-test not in list: {r}"

    r = json.loads(h({"action": "check", "mode": "integ-test"}))
    assert r["active"] is True

    r = json.loads(h({"action": "cancel", "mode": "integ-test", "reason": "integration test"}))
    assert r["success"] is True

    r = json.loads(h({"action": "cancel_check", "mode": "integ-test"}))
    assert r["cancelled"] is True

    r = json.loads(h({"action": "clear", "mode": "integ-test"}))
    assert r["cleared"] is True


@test("omh_gather_evidence tool: runs echo command")
def _():
    from tools.registry import registry
    h = registry._tools["omh_gather_evidence"].handler
    r = json.loads(h({"commands": ["echo integration-test"]}))
    assert "error" not in r, f"evidence error: {r}"
    assert r["all_pass"] is True
    assert "integration-test" in r["results"][0]["output"]


@test("omh_gather_evidence tool: rejects disallowed commands")
def _():
    from tools.registry import registry
    h = registry._tools["omh_gather_evidence"].handler
    r = json.loads(h({"commands": ["rm -rf /"]}))
    assert "error" in r
    assert "rm -rf /" in r["rejected"]


@test("pre_llm_call hook: returns context when modes active")
def _():
    from tools.registry import registry
    h = registry._tools["omh_state"].handler
    h({"action": "write", "mode": "ralph", "data": {"active": True, "phase": "execute"}})

    for key, mod in sys.modules.items():
        if key.endswith("omh_state") and hasattr(mod, "_list_cache"):
            mod._list_cache["expires_at"] = 0.0

    results = manager.invoke_hook("pre_llm_call", is_first_turn=True)
    assert len(results) >= 1, "pre_llm_call returned no results"
    assert "context" in results[0]
    assert "ralph" in results[0]["context"]

    h({"action": "clear", "mode": "ralph"})


@test("on_session_end hook: writes _interrupted_at")
def _():
    from tools.registry import registry
    h = registry._tools["omh_state"].handler
    h({"action": "write", "mode": "ralph", "data": {"active": True, "phase": "execute"}})

    for key, mod in sys.modules.items():
        if key.endswith("omh_state") and hasattr(mod, "_list_cache"):
            mod._list_cache["expires_at"] = 0.0

    manager.invoke_hook("on_session_end")

    r = json.loads(h({"action": "read", "mode": "ralph"}))
    assert "_interrupted_at" in r["data"], f"_interrupted_at not set: {r['data']}"

    h({"action": "clear", "mode": "ralph"})


# ---- Summary -------------------------------------------------------------

print("-" * 60)
print(f"Results: {PASSED} passed, {FAILED} failed")
if ERRORS:
    print("\nFailed tests:")
    for name, err in ERRORS:
        print(f"  - {name}: {err}")
    sys.exit(1)
else:
    print("\nAll integration tests passed!")
    sys.exit(0)
