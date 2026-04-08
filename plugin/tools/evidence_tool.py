"""
omh_gather_evidence tool — run build/test/lint commands and collect structured output.

Commands must match the configured allowlist prefixes (safety rail).
Output is truncated to keep the tail (most relevant for build/test failures).
"""

import json
import logging
import re
import shlex
import subprocess
from pathlib import Path

from ..omh_config import get_config

logger = logging.getLogger(__name__)

# Shell metacharacters that allow command chaining/injection.
# A command containing any of these is rejected regardless of allowlist prefix.
# Single & and | already block && and || — no separate alternation needed.
_SHELL_METACHAR_RE = re.compile(r"[\n\r;&|`$<>(){}]")

_MAX_TIMEOUT = 300       # 5 minutes absolute max regardless of LLM-supplied value
_MAX_TRUNCATE = 50_000   # 50KB max per command output


def _matches_allowlist(cmd_tokens: list[str], allowlist: list[str]) -> bool:
    """Token-level allowlist check — prevents partial-word and argument-injection bypass.

    Splits each allowlist entry on whitespace and requires the command's leading tokens
    to match exactly. 'npm test' matches ['npm', 'test', '--verbose'] but NOT
    ['npm', 'testing-malicious-package'].
    """
    for prefix in allowlist:
        prefix_tokens = prefix.split()
        if not prefix_tokens:
            continue
        if len(cmd_tokens) < len(prefix_tokens):
            continue
        if cmd_tokens[:len(prefix_tokens)] == prefix_tokens:
            return True
    return False

OMH_EVIDENCE_SCHEMA = {
    "name": "omh_gather_evidence",
    "description": (
        "Run build/test/lint commands and collect evidence for verification. "
        "Commands must match the configured allowlist (build tools, test runners, linters). "
        "Returns structured results with exit codes, truncated output (tail), "
        "and an all_pass summary."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Commands to run (must match configured allowlist via token-prefix check)",
            },
            "truncate": {
                "type": "integer",
                "description": "Max chars per command output, keeps tail (default: 2000)",
            },
            "workdir": {
                "type": "string",
                "description": "Working directory (default: current directory)",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout per command in seconds (default: 120)",
            },
        },
        "required": ["commands"],
    },
}


def omh_evidence_handler(args: dict, **kwargs) -> str:
    config = get_config()
    ev_cfg = config.get("evidence", {})
    allowlist = ev_cfg.get("allowlist_prefixes", [])
    max_cmds = ev_cfg.get("max_commands", 10)
    default_truncate = ev_cfg.get("default_truncate", 2000)
    default_timeout = ev_cfg.get("default_timeout", 120)

    commands = args.get("commands", [])
    truncate = args.get("truncate", default_truncate)
    timeout = args.get("timeout", default_timeout)

    timeout = min(timeout, _MAX_TIMEOUT)
    truncate = min(truncate, _MAX_TRUNCATE)

    # Validate workdir stays within the project root (prevents escaping cwd via tool args)
    workdir_arg = args.get("workdir") or None
    workdir = None
    if workdir_arg:
        resolved = Path(workdir_arg).resolve()
        project_root = Path.cwd().resolve()
        if not resolved.is_relative_to(project_root):
            return json.dumps({
                "error": f"workdir must be within project root",
                "workdir": workdir_arg,
            })
        workdir = str(resolved)

    if not commands:
        return json.dumps({"error": "commands list is empty"})

    if len(commands) > max_cmds:
        return json.dumps({"error": f"Too many commands: {len(commands)} > {max_cmds}"})

    # Reject commands containing shell metacharacters (injection prevention).
    # The allowlist uses startswith() which is bypassable via ; && || | etc.
    chained = [cmd for cmd in commands if _SHELL_METACHAR_RE.search(cmd)]
    if chained:
        logger.debug("Rejected commands containing shell metacharacters: %s", chained)
        return json.dumps({
            "error": "Commands containing shell metacharacters are not allowed",
            "rejected": chained,
            "hint": "Use simple commands without ; && || | ` $( ) { } characters",
        })

    # Allowlist check — token-based to prevent partial-word and argument-injection bypass.
    rejected = []
    parsed_commands: list[tuple[str, list[str]]] = []
    for cmd in commands:
        try:
            tokens = shlex.split(cmd)
        except ValueError as e:
            return json.dumps({
                "error": f"Command could not be parsed: {e}",
                "rejected": [cmd],
            })
        if not _matches_allowlist(tokens, allowlist):
            rejected.append(cmd)
        else:
            parsed_commands.append((cmd, tokens))

    if rejected:
        logger.debug("Rejected commands not in allowlist: %s", rejected)
        return json.dumps({
            "error": "Commands not in allowlist",
            "rejected": rejected,
            "hint": "Add prefixes to config.yaml evidence.allowlist_prefixes",
        })

    results = []
    for cmd, tokens in parsed_commands:
        try:
            proc = subprocess.run(
                tokens,
                shell=False,
                capture_output=True,
                text=True,
                cwd=workdir,
                timeout=timeout,
            )
            combined = proc.stdout + proc.stderr
            truncated = len(combined) > truncate
            output = combined[-truncate:] if truncated else combined
            results.append({
                "command": cmd,
                "exit_code": proc.returncode,
                "output": output,
                "truncated": truncated,
                "passed": proc.returncode == 0,
            })
        except subprocess.TimeoutExpired:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "output": f"TIMEOUT after {timeout}s",
                "truncated": False,
                "passed": False,
            })
        except Exception as e:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "output": f"ERROR: {e}",
                "truncated": False,
                "passed": False,
            })

    passed_count = sum(1 for r in results if r["passed"])
    return json.dumps({
        "results": results,
        "all_pass": all(r["passed"] for r in results),
        "summary": f"{passed_count}/{len(results)} passed",
    })
