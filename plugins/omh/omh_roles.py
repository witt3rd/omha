"""
Role catalog for OMH plugin — loads role prompt files from the centralized
references/ directory bundled with the plugin.

Provides:
  extract_role_marker(text)  — parse [omh-role:NAME] from a string
  load_role_prompt(role)     — read role-{name}.md content
  get_role_catalog()         — {name: Path} map of all available roles
"""

import re
from pathlib import Path

# Validates role names: alphanumeric, hyphens, underscores only.
# Prevents path traversal (e.g. "../../etc/passwd" is rejected).
ROLE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Detects [omh-role:NAME] markers in goal strings.
ROLE_MARKER_RE = re.compile(r"\[omh-role:([a-zA-Z0-9_-]+)\]")

_REFERENCES_DIR = Path(__file__).parent / "references"


def get_role_catalog() -> dict[str, Path]:
    """Return {role_name: path} for all role-*.md files in references/."""
    if not _REFERENCES_DIR.exists():
        return {}
    return {
        p.stem.removeprefix("role-"): p
        for p in sorted(_REFERENCES_DIR.glob("role-*.md"))
    }


def load_role_prompt(role_name: str) -> str | None:
    """Read and return role prompt content. Returns None if unknown or invalid."""
    if not ROLE_NAME_RE.match(role_name):
        return None
    catalog = get_role_catalog()
    path = catalog.get(role_name)
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def extract_role_marker(text: str) -> str | None:
    """Extract the first [omh-role:NAME] marker from text. Returns name or None."""
    m = ROLE_MARKER_RE.search(text)
    return m.group(1) if m else None
