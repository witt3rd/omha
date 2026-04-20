"""Tests for omh_config.py — _deep_merge and get_config edge cases."""

import pytest
import plugins.omh.omh_config as omh_config_module
from plugins.omh.omh_config import _deep_merge, get_config, reload_config


@pytest.fixture(autouse=True)
def reset_cache():
    omh_config_module._config_cache = None
    yield
    omh_config_module._config_cache = None


# ---------------------------------------------------------------------------
# _deep_merge — direct unit tests
# ---------------------------------------------------------------------------

def test_deep_merge_flat_override_replaces_value():
    result = _deep_merge({"a": 1, "b": 2}, {"b": 99})
    assert result == {"a": 1, "b": 99}


def test_deep_merge_nested_dict_merged_recursively():
    base = {"evidence": {"max_commands": 10, "default_timeout": 120}}
    override = {"evidence": {"max_commands": 5}}
    result = _deep_merge(base, override)
    assert result["evidence"]["max_commands"] == 5
    assert result["evidence"]["default_timeout"] == 120  # preserved


def test_deep_merge_non_dict_overrides_dict():
    result = _deep_merge({"a": {"nested": 1}}, {"a": "flat"})
    assert result["a"] == "flat"


def test_deep_merge_new_key_added():
    result = _deep_merge({"a": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    _deep_merge(base, override)
    assert "y" not in base["a"]


def test_deep_merge_returns_copy_not_same_object():
    base = {"a": 1}
    result = _deep_merge(base, {})
    assert result == base
    assert result is not base


def test_deep_merge_empty_base():
    result = _deep_merge({}, {"a": 1})
    assert result == {"a": 1}


def test_deep_merge_empty_override():
    result = _deep_merge({"a": 1}, {})
    assert result == {"a": 1}


# ---------------------------------------------------------------------------
# get_config — YAML loading and fallback paths
# ---------------------------------------------------------------------------

def test_get_config_loads_yaml_override(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("staleness_hours: 99\n")
    monkeypatch.setattr(omh_config_module, "_find_config_file", lambda: cfg_file)
    config = get_config()
    assert config["staleness_hours"] == 99


def test_get_config_yaml_nested_override_merges(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("evidence:\n  max_commands: 3\n")
    monkeypatch.setattr(omh_config_module, "_find_config_file", lambda: cfg_file)
    config = get_config()
    assert config["evidence"]["max_commands"] == 3


def test_get_config_parse_error_returns_empty(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(": invalid: yaml: {{\n")
    monkeypatch.setattr(omh_config_module, "_find_config_file", lambda: cfg_file)
    config = get_config()
    assert config == {}


def test_get_config_returns_same_object_on_second_call():
    first = get_config()
    second = get_config()
    assert first is second


def test_get_config_no_config_file_returns_empty(monkeypatch):
    monkeypatch.setattr(omh_config_module, "_find_config_file", lambda: None)
    config = get_config()
    assert config == {}


def test_get_config_yaml_import_error_returns_empty(tmp_path, monkeypatch):
    import builtins
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("staleness_hours: 99\n")
    monkeypatch.setattr(omh_config_module, "_find_config_file", lambda: cfg_file)
    real_import = builtins.__import__
    def block_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", block_yaml)
    config = get_config()
    assert config == {}


def test_reload_config_clears_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(omh_config_module, "_find_config_file", lambda: None)
    first = get_config()
    assert first is not None
    reload_config()
    second = get_config()
    assert second is not None
