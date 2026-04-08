"""
OMH Config Loader — reads plugin/config.yaml (or installed copy), merges with defaults.

Config is cached after first load. Call get_config() from any module.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_config_cache: dict[str, Any] | None = None

# NOTE: Keep _DEFAULTS in sync with plugin/config.yaml.
# _DEFAULTS is the fallback when PyYAML is unavailable or config.yaml fails to load.
# config.yaml is the installed config that users can customize.
_DEFAULTS: dict[str, Any] = {
    "role_prompts_dir": "~/.hermes/skills/omh-ralplan/references",
    "roles": {
        "executor":          {"category": "implementation"},
        "verifier":          {"category": "review"},
        "architect":         {"category": "analysis"},
        "planner":           {"category": "planning"},
        "critic":            {"category": "analysis"},
        "analyst":           {"category": "analysis"},
        "security-reviewer": {"category": "review"},
        "code-reviewer":     {"category": "review"},
        "test-engineer":     {"category": "testing"},
        "debugger":          {"category": "analysis"},
    },
    "state_dir": ".omh/state",
    "staleness_hours": 2,
    "cancel_ttl_seconds": 30,
    "evidence": {
        "allowlist_prefixes": [
            # npm — specific subcommands only
            "npm test", "npm run test", "npm run build", "npm run lint",
            "npm run typecheck", "npm run check",
            # npx — specific trusted runners only
            "npx jest", "npx vitest", "npx mocha", "npx eslint", "npx tsc",
            # yarn / pnpm
            "yarn test", "yarn build", "yarn lint",
            "pnpm test", "pnpm build", "pnpm lint",
            # Rust
            "cargo test", "cargo build", "cargo check", "cargo clippy",
            "rustfmt --check",
            # Go
            "go test", "go build", "go vet",
            # Python
            "python -m pytest", "python -m mypy",
            "python3 -m pytest", "python3 -m mypy",
            "uv run pytest", "uv run mypy",
            # Linters / formatters
            "ruff check", "ruff format --check", "black --check", "eslint", "tsc",
            "prettier --check",
            # Make — specific safe targets only
            "make test", "make build", "make check", "make lint",
        ],
        "max_commands": 10,
        "default_timeout": 120,
        "default_truncate": 2000,
    },
}


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
    """Return merged config dict (defaults + config.yaml). Cached after first call."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config = dict(_DEFAULTS)
    path = _find_config_file()
    if path:
        try:
            import yaml  # optional dependency
            with open(path, encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            config = _deep_merge(config, user_cfg)
        except ImportError:
            logger.debug("PyYAML not installed; using default OMH config")
        except Exception as e:
            logger.warning("Failed to load OMH config from %s: %s", path, e)

    _config_cache = config
    return _config_cache


def reload_config() -> dict[str, Any]:
    """Force reload from disk (useful for tests)."""
    global _config_cache
    _config_cache = None
    return get_config()
