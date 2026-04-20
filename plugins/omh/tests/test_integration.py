"""Integration tests — load OMH plugin through the actual Hermes PluginManager.

Run with the Hermes venv to validate the full plugin lifecycle:
    ~/.hermes/hermes-agent/venv/bin/python3 -m pytest plugin/tests/test_integration.py -v

These tests verify:
  1. Plugin loads without errors through Hermes plugin discovery
  2. Tools are registered with correct names, schemas, and callable handlers
  3. Hooks are registered for the correct lifecycle events
  4. Tool handlers produce valid JSON responses when called
  5. Hook callbacks return the expected format
"""

import importlib
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Detect Hermes availability
# ---------------------------------------------------------------------------

HERMES_AGENT_DIR = Path.home() / ".hermes" / "hermes-agent"
HERMES_AVAILABLE = HERMES_AGENT_DIR.is_dir()

if HERMES_AVAILABLE:
    # Add Hermes source to sys.path so we can import its plugin system
    hermes_src = str(HERMES_AGENT_DIR)
    if hermes_src not in sys.path:
        sys.path.insert(0, hermes_src)

skip_no_hermes = pytest.mark.skipif(
    not HERMES_AVAILABLE,
    reason="Hermes not installed at ~/.hermes/hermes-agent",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plugin_dir():
    """Return the absolute path to the plugin directory."""
    return Path(__file__).resolve().parent.parent


_TEST_CONFIG = {
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


def _patch_all_config_modules(value):
    """Patch _config_cache on every omh_config module instance in sys.modules.

    Hermes loads the plugin as hermes_plugins.omh.*, creating separate module
    instances from the plugin.* namespace. Both need the same config patch.
    """
    for key, mod in sys.modules.items():
        if key.endswith("omh_config") and hasattr(mod, "_config_cache"):
            mod._config_cache = value


def _reset_all_list_caches():
    """Reset _list_cache on every omh_state module instance in sys.modules."""
    for key, mod in sys.modules.items():
        if key.endswith("omh_state") and hasattr(mod, "_list_cache"):
            mod._list_cache["result"] = None
            mod._list_cache["expires_at"] = 0.0


@pytest.fixture
def isolated_workdir(tmp_path, monkeypatch):
    """Run in a temp directory so state files don't pollute the repo."""
    monkeypatch.chdir(tmp_path)
    _patch_all_config_modules(dict(_TEST_CONFIG))
    _reset_all_list_caches()
    yield tmp_path
    _patch_all_config_modules(None)
    _reset_all_list_caches()


# ---------------------------------------------------------------------------
# Test: Plugin loads through Hermes PluginManager
# ---------------------------------------------------------------------------

@skip_no_hermes
def test_plugin_loads_via_hermes_plugin_manager(plugin_dir):
    """Load the OMH plugin using the actual Hermes PluginManager."""
    from hermes_cli.plugins import PluginManager, PluginManifest

    manager = PluginManager()
    manifest = PluginManifest(
        name="omh",
        version="0.1.0",
        description="Oh My Hermes integration test",
        source="project",
        path=str(plugin_dir),
    )

    manager._load_plugin(manifest)

    loaded = manager._plugins.get("omh")
    assert loaded is not None, "Plugin 'omh' not found in manager._plugins"
    assert loaded.enabled is True, f"Plugin failed to load: {loaded.error}"
    assert loaded.error is None


@skip_no_hermes
def test_tools_registered_in_hermes_registry(plugin_dir):
    """Verify both tools appear in the Hermes tool registry after loading."""
    from hermes_cli.plugins import PluginManager, PluginManifest

    manager = PluginManager()
    manifest = PluginManifest(
        name="omh",
        version="0.1.0",
        source="project",
        path=str(plugin_dir),
    )
    manager._load_plugin(manifest)

    assert "omh_state" in manager._plugin_tool_names
    assert "omh_gather_evidence" in manager._plugin_tool_names

    # Verify tools are in the global registry with correct toolset
    from tools.registry import registry
    state_entry = registry._tools.get("omh_state")
    assert state_entry is not None, "omh_state not found in tools.registry"
    assert state_entry.toolset == "omh"
    assert callable(state_entry.handler)
    assert isinstance(state_entry.schema, dict)
    assert state_entry.schema.get("name") == "omh_state"

    evidence_entry = registry._tools.get("omh_gather_evidence")
    assert evidence_entry is not None, "omh_gather_evidence not found in tools.registry"
    assert evidence_entry.toolset == "omh"
    assert callable(evidence_entry.handler)
    assert isinstance(evidence_entry.schema, dict)


@skip_no_hermes
def test_hooks_registered_in_hermes(plugin_dir):
    """Verify both hooks are registered with the PluginManager."""
    from hermes_cli.plugins import PluginManager, PluginManifest

    manager = PluginManager()
    manifest = PluginManifest(
        name="omh",
        version="0.1.0",
        source="project",
        path=str(plugin_dir),
    )
    manager._load_plugin(manifest)

    assert "pre_llm_call" in manager._hooks, "pre_llm_call hook not registered"
    assert len(manager._hooks["pre_llm_call"]) >= 1
    assert "on_session_end" in manager._hooks, "on_session_end hook not registered"
    assert len(manager._hooks["on_session_end"]) >= 1


# ---------------------------------------------------------------------------
# Test: Tool dispatch through Hermes registry
# ---------------------------------------------------------------------------

@skip_no_hermes
def test_omh_state_tool_dispatch_via_registry(plugin_dir, isolated_workdir):
    """Call omh_state handler through the Hermes registry and verify JSON response."""
    from hermes_cli.plugins import PluginManager, PluginManifest
    from tools.registry import registry

    manager = PluginManager()
    manifest = PluginManifest(name="omh", version="0.1.0", source="project", path=str(plugin_dir))
    manager._load_plugin(manifest)

    entry = registry._tools["omh_state"]

    # Write state
    result = json.loads(entry.handler({"action": "write", "mode": "test-integ", "data": {"active": True, "phase": "testing"}}))
    assert result["success"] is True

    # Read state back
    result = json.loads(entry.handler({"action": "read", "mode": "test-integ"}))
    assert result["exists"] is True
    assert result["data"]["active"] is True
    assert result["data"]["phase"] == "testing"

    # List active
    result = json.loads(entry.handler({"action": "list"}))
    assert any(m["mode"] == "test-integ" for m in result["modes"])

    # Check
    result = json.loads(entry.handler({"action": "check", "mode": "test-integ"}))
    assert result["active"] is True

    # Cancel
    result = json.loads(entry.handler({"action": "cancel", "mode": "test-integ", "reason": "integration test"}))
    assert result["success"] is True

    # Cancel check
    result = json.loads(entry.handler({"action": "cancel_check", "mode": "test-integ"}))
    assert result["cancelled"] is True

    # Clear
    result = json.loads(entry.handler({"action": "clear", "mode": "test-integ"}))
    assert result["cleared"] is True


@skip_no_hermes
def test_omh_evidence_tool_dispatch_via_registry(plugin_dir, isolated_workdir):
    """Call omh_gather_evidence handler through the Hermes registry."""
    from hermes_cli.plugins import PluginManager, PluginManifest
    from tools.registry import registry

    manager = PluginManager()
    manifest = PluginManifest(name="omh", version="0.1.0", source="project", path=str(plugin_dir))
    manager._load_plugin(manifest)

    entry = registry._tools["omh_gather_evidence"]
    result = json.loads(entry.handler({"commands": ["echo integration-test"]}))
    assert "error" not in result
    assert result["all_pass"] is True
    assert result["results"][0]["output"].strip() == "integration-test"


# ---------------------------------------------------------------------------
# Test: Hook invocation through Hermes invoke_hook
# ---------------------------------------------------------------------------

@skip_no_hermes
def test_pre_llm_call_hook_via_invoke(plugin_dir, isolated_workdir):
    """Test pre_llm_call returns context when modes are active."""
    from hermes_cli.plugins import PluginManager, PluginManifest
    from tools.registry import registry

    manager = PluginManager()
    manifest = PluginManifest(name="omh", version="0.1.0", source="project", path=str(plugin_dir))
    manager._load_plugin(manifest)

    # Write an active mode
    state_entry = registry._tools["omh_state"]
    state_entry.handler({"action": "write", "mode": "ralph", "data": {"active": True, "phase": "execute"}})

    # Invoke hook — first turn
    from plugins.omh.omh_state import _invalidate_list_cache
    _invalidate_list_cache()
    results = manager.invoke_hook("pre_llm_call", is_first_turn=True)
    assert len(results) >= 1
    ctx = results[0]
    assert "context" in ctx
    assert "ralph" in ctx["context"]
    assert "Active modes" in ctx["context"] or "OMH" in ctx["context"]

    # Invoke hook — subsequent turn
    _invalidate_list_cache()
    results = manager.invoke_hook("pre_llm_call", is_first_turn=False)
    assert len(results) >= 1
    ctx = results[0]
    assert "context" in ctx
    assert "ralph" in ctx["context"]


@skip_no_hermes
def test_on_session_end_hook_via_invoke(plugin_dir, isolated_workdir):
    """Test on_session_end writes _interrupted_at to active state files."""
    from hermes_cli.plugins import PluginManager, PluginManifest
    from tools.registry import registry

    manager = PluginManager()
    manifest = PluginManifest(name="omh", version="0.1.0", source="project", path=str(plugin_dir))
    manager._load_plugin(manifest)

    # Write an active mode
    state_entry = registry._tools["omh_state"]
    state_entry.handler({"action": "write", "mode": "ralph", "data": {"active": True, "phase": "execute"}})

    # Invoke on_session_end
    from plugins.omh.omh_state import _invalidate_list_cache
    _invalidate_list_cache()
    manager.invoke_hook("on_session_end")

    # Verify _interrupted_at was written
    result = json.loads(state_entry.handler({"action": "read", "mode": "ralph"}))
    assert "_interrupted_at" in result["data"]


# ---------------------------------------------------------------------------
# Contract test: validate our register() matches Hermes PluginContext API
# ---------------------------------------------------------------------------

def test_register_tool_signature_matches_hermes_contract(plugin_dir, monkeypatch):
    """Verify our register() calls ctx.register_tool with the correct arity.

    This test works even WITHOUT Hermes installed by mocking the ctx object
    and verifying the call signature. _install_skills is monkeypatched to a
    no-op to avoid writing into the real ~/.hermes/skills/ directory.
    """
    import plugins.omh as omh_plugin
    monkeypatch.setattr(omh_plugin, "_install_skills", lambda: None)

    calls = {"tools": [], "hooks": []}

    class MockCtx:
        def register_tool(self, name, toolset, schema, handler, **kwargs):
            assert isinstance(name, str), f"name should be str, got {type(name)}"
            assert isinstance(toolset, str), f"toolset should be str, got {type(toolset)}"
            assert isinstance(schema, dict), f"schema should be dict, got {type(schema)}"
            assert callable(handler), f"handler should be callable, got {type(handler)}"
            calls["tools"].append({"name": name, "toolset": toolset, "schema": schema, "handler": handler, "kwargs": kwargs})

        def register_hook(self, hook_name, callback):
            assert isinstance(hook_name, str)
            assert callable(callback)
            calls["hooks"].append({"hook_name": hook_name, "callback": callback})

    omh_plugin.register(MockCtx())

    # Verify tools
    tool_names = [t["name"] for t in calls["tools"]]
    assert "omh_state" in tool_names
    assert "omh_gather_evidence" in tool_names

    for t in calls["tools"]:
        assert t["toolset"] == "omh", f"Tool {t['name']} has wrong toolset: {t['toolset']}"
        assert "name" in t["schema"], f"Tool {t['name']} schema missing 'name' field"
        assert "parameters" in t["schema"], f"Tool {t['name']} schema missing 'parameters' field"

    for t in calls["tools"]:
        assert "description" in t["kwargs"], f"Tool {t['name']} missing description kwarg"
        assert isinstance(t["kwargs"]["description"], str)
        assert len(t["kwargs"]["description"]) > 0

    # Verify hooks
    hook_names = [h["hook_name"] for h in calls["hooks"]]
    assert "pre_llm_call" in hook_names
    assert "on_session_end" in hook_names


# ---------------------------------------------------------------------------
# Test: Tool schemas are valid for LLM tool-calling
# ---------------------------------------------------------------------------

def test_tool_schemas_valid_for_llm():
    """Verify tool schemas have the required fields for Hermes tool-calling."""
    from plugins.omh.tools.state_tool import OMH_STATE_SCHEMA
    from plugins.omh.tools.evidence_tool import OMH_EVIDENCE_SCHEMA

    for schema in [OMH_STATE_SCHEMA, OMH_EVIDENCE_SCHEMA]:
        assert "name" in schema, "Schema missing 'name'"
        assert "description" in schema, "Schema missing 'description'"
        assert "parameters" in schema, "Schema missing 'parameters'"

        params = schema["parameters"]
        assert params.get("type") == "object", "parameters.type must be 'object'"
        assert "properties" in params, "parameters missing 'properties'"
        assert isinstance(params["properties"], dict), "parameters.properties must be dict"
