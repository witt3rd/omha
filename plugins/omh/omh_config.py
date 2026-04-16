"""
OMH Config Loader — reads plugin/config.yaml (or installed copy).

Config is cached after first load. Call get_config() from any module.
config.yaml is the single source of truth — there is no hardcoded Python fallback.
If config.yaml is missing or unreadable, get_config() returns {}.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_config_cache: dict[str, Any] | None = None


def _find_config_file() -> Path | None:
    """Search for config.yaml in plugin dir or installed location."""
    candidates = [
        Path(__file__).parent / "config.yaml",
        Path("~/.hermes/plugins/omh/config.yaml").expanduser(),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursively for nested dicts."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def get_config() -> dict[str, Any]:
    """Return config dict loaded from config.yaml. Cached after first call.
    Returns {} if config.yaml is missing, unreadable, or PyYAML is not installed.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config: dict[str, Any] = {}
    path = _find_config_file()
    if path:
        try:
            import yaml  # optional dependency
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except ImportError:
            logger.warning("PyYAML is required for OMH config loading (pip install pyyaml)")
        except Exception as e:
            logger.warning("Failed to load OMH config from %s: %s", path, e)

    _config_cache = config
    return _config_cache


def reload_config() -> dict[str, Any]:
    """Force reload from disk (useful for tests)."""
    global _config_cache
    _config_cache = None
    return get_config()
