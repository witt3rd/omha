#!/usr/bin/env bash
# Run integration tests using the Hermes venv Python.
# This validates the plugin against the actual Hermes runtime.
#
# Usage: ./plugin/tests/run_integration.sh
#
set -euo pipefail

HERMES_VENV="${HOME}/.hermes/hermes-agent/venv/bin/python3"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ ! -x "$HERMES_VENV" ]; then
  echo "ERROR: Hermes venv not found at $HERMES_VENV"
  echo "Install Hermes first: https://hermes-agent.nousresearch.com"
  exit 1
fi

echo "Running integration tests with Hermes venv: $HERMES_VENV"
cd "$REPO_ROOT"
PYTHONPATH="$REPO_ROOT" exec "$HERMES_VENV" plugin/tests/integration_runner.py "$@"
