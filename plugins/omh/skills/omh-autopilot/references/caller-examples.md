# Autopilot Caller Loop Examples

Autopilot is one-phase-step-per-invocation. These examples show how to drive it.

## Manual CLI

```bash
# Start autopilot
hermes chat --message "autopilot: build a Python CLI that converts CSV to JSON"

# After it exits, re-invoke until complete
hermes chat --message "continue autopilot"
hermes chat --message "continue autopilot"
# ... repeat until it reports "Phase 5: Complete"
```

Check progress anytime:
```bash
cat .omh/state/autopilot-state.json | python3 -m json.tool
```

## Shell Script Loop

```bash
#!/bin/bash
# autopilot-loop.sh — Drive autopilot to completion

PROJECT_DIR="$(pwd)"
STATE_FILE="$PROJECT_DIR/.omh/state/autopilot-state.json"

# Initial invocation (or resume)
while true; do
    hermes chat --message "continue autopilot for $PROJECT_DIR"

    # Check if complete or blocked
    if [ ! -f "$STATE_FILE" ]; then
        echo "Autopilot complete (state file cleaned up)"
        break
    fi

    PHASE=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['phase'])" 2>/dev/null)

    if [ "$PHASE" = "complete" ]; then
        echo "Autopilot complete"
        break
    elif [ "$PHASE" = "blocked" ]; then
        echo "Autopilot blocked — check $STATE_FILE for details"
        break
    elif [ "$PHASE" = "paused" ]; then
        echo "Autopilot paused for review — check state and re-run when ready"
        break
    fi

    # Brief pause between invocations
    sleep 5
done
```

## Hermes Cron Job

```bash
# Schedule autopilot to run every 2 minutes
hermes cron create \
    --schedule "every 2m" \
    --prompt "Continue autopilot execution in $(pwd). Read .omh/state/autopilot-state.json and perform the next step." \
    --name "autopilot-$(basename $(pwd))"
```

Stop the cron when done:
```bash
hermes cron list
hermes cron remove <job-id>
```

## Handling Blocked State

When autopilot reports blocked:
1. Read the state: `cat .omh/state/autopilot-state.json`
2. Check ralph state if in Phase 2: `cat .omh/state/ralph-state.json`
3. Fix the underlying issue
4. Re-invoke: `hermes chat --message "continue autopilot"`

## Handling Phase 0 Interactivity

If Phase 0 (requirements) starts a deep interview, you must participate:
1. Answer the interview questions interactively
2. Confirm the spec when prompted
3. Subsequent invocations (Phases 1-5) are autonomous

For fully automated runs, pre-create a spec:
```bash
hermes chat --message "deep interview: <your idea>"
# Complete the interview, confirm the spec
# Then start autopilot — it will detect the spec and skip Phase 0
hermes chat --message "autopilot: continue"
```
