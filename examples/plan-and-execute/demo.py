#!/usr/bin/env python3
"""
OMH Plugin — Hermes Agent Demo (Plan + Execute Pipeline)
=========================================================
Runs a real Hermes agent session showing the full OMH pipeline:

  omh-ralplan  →  builds a consensus plan (Planner + Architect + Critic)
  omh-ralph    →  executes the plan task-by-task with verified evidence

The agent receives a plain-language request and handles everything:
planning, implementation, and verification using omh_state and
omh_gather_evidence from the OMH plugin.

Setup:
  1. Creates an empty Python project workdir
  2. Symlinks plugins/omh/ into .hermes/plugins/omh/ (project plugin)
  3. Loads omh-ralplan + omh-ralph skills
  4. Runs: hermes chat --skills omh-ralplan,omh-ralph -q "<request>"

Requirements:
  - Hermes Agent at ~/.hermes/hermes-agent/
  - omh-ralplan + omh-ralph skills installed:
      hermes skills install omh-ralplan
      hermes skills install omh-ralph
  - An inference provider configured:
      hermes model    (interactive setup)
      hermes login    (authenticate)

Run:
    ./examples/run.sh --hermes
    python3 examples/hermes_integration.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HERMES_BIN = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes"
PLUGIN_SRC = REPO_ROOT / "plugins" / "omh"

REQUIRED_SKILLS = {
    "omh-ralplan": Path.home() / ".hermes" / "skills" / "omh-ralplan",
    "omh-ralph":   Path.home() / ".hermes" / "skills" / "omh-ralph",
}

if not HERMES_BIN.exists():
    print("ERROR: Hermes not found at ~/.hermes/hermes-agent/venv/bin/hermes", flush=True)
    print("Install Hermes: https://github.com/NousResearch/hermes-agent", flush=True)
    sys.exit(1)

missing = [name for name, path in REQUIRED_SKILLS.items() if not path.exists()]
if missing:
    print(f"ERROR: Missing skills: {', '.join(missing)}", flush=True)
    for name in missing:
        print(f"  hermes skills install {name}", flush=True)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Set up an empty Python project workdir
# ---------------------------------------------------------------------------

WORKDIR = Path(tempfile.mkdtemp(prefix="omh-demo-"))

# OMH plugin: .hermes/plugins/omh -> repo plugins/omh
plugin_link = WORKDIR / ".hermes" / "plugins" / "omh"
plugin_link.parent.mkdir(parents=True)
plugin_link.symlink_to(PLUGIN_SRC)

# Minimal project context so ralplan knows the tech stack and constraints
(WORKDIR / "README.md").write_text(
    "# expense-tracker\n"
    "A CLI expense tracker written in Python (stdlib only — no third-party dependencies).\n"
    "Data is stored in a local JSON file. Tests use pytest.\n"
)

print("Hermes plan + execute demo", flush=True)
print(f"Plugin:   {PLUGIN_SRC}", flush=True)
print(f"Skills:   {', '.join(REQUIRED_SKILLS)}", flush=True)
print(f"Workdir:  {WORKDIR}", flush=True)
print(flush=True)

# ---------------------------------------------------------------------------
# Natural user request — no pre-built plan, no stubs
# ---------------------------------------------------------------------------

QUERY = (
    "Build a CLI expense tracker in Python. "
    "It should support: adding expenses (amount, category, description), "
    "listing expenses with optional category filter, deleting by ID, "
    "and a monthly summary report. "
    "Store data in a local JSON file — no database or third-party dependencies. "
    "Use ralplan to create a consensus plan first, then use ralph to implement it."
)

print(f"Query: {QUERY!r}", flush=True)
print(flush=True)

# ---------------------------------------------------------------------------
# Run Hermes
# ---------------------------------------------------------------------------

env = {
    **os.environ,
    "HERMES_ENABLE_PROJECT_PLUGINS": "1",
    "HERMES_QUIET": "1",
}

proc = subprocess.Popen(
    [
        str(HERMES_BIN), "chat",
        "--skills", "omh-ralplan,omh-ralph",
        "-q", QUERY,
        "--yolo",
    ],
    cwd=str(WORKDIR),
    env=env,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

output_lines = []
for line in proc.stdout:
    print(line, end="", flush=True)
    output_lines.append(line)

proc.wait()
output = "".join(output_lines)

if "No inference provider configured" in output:
    print(
        "\n--- Setup required ---\n"
        "Hermes needs an inference provider to run the agent demo.\n"
        "\n"
        "Quick setup (pick one):\n"
        "  hermes model                         # interactive provider selection\n"
        "  export OPENROUTER_API_KEY=sk-or-...  # OpenRouter\n"
        "  export OPENAI_API_KEY=sk-...         # OpenAI\n"
        "  export ANTHROPIC_API_KEY=sk-ant-...  # Anthropic\n"
        "\n"
        "Then re-run: ./examples/run.sh --hermes",
        flush=True,
    )
    sys.exit(1)

sys.exit(proc.returncode)
