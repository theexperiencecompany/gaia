#!/usr/bin/env bash
# gaia-hook: save, then relay one coding-agent event to GAIA.
#
# Claude Code runs it as its Stop/StopFailure/Notification command hook and the
# OpenCode plugin pipes {kind, raw} into it, so both CLIs share one path. The
# event JSON arrives on stdin. Saving first means the todo the event wakes reads
# the agent's current state. A failed save is reported as its own event.
# Always exits 0: a Stop hook exiting 2 would make Claude keep going.
set -uo pipefail

payload="$(cat)"

post() {
    curl -fsS -m 15 -X POST "$GAIA_LAB_CALLBACK_URL" \
        -H "Authorization: Bearer $GAIA_LAB_TOKEN" \
        -H "Content-Type: application/json" \
        --data-binary @- >/dev/null
}

if ! save_error="$(timeout {{SAVE_TIMEOUT_SECONDS}} "{{SAVE_SCRIPT}}" 2>&1)"; then
    echo "gaia-hook: save failed: $save_error" >&2
    save_failed=1
fi

if [ -z "${GAIA_LAB_CALLBACK_URL:-}" ] || [ -z "${GAIA_LAB_TOKEN:-}" ]; then
    echo "gaia-hook: no run env (GAIA_LAB_CALLBACK_URL/GAIA_LAB_TOKEN); saved, not relayed" >&2
    exit 0
fi

if [ -n "${save_failed:-}" ]; then
    printf '%s' "$save_error" | tail -c 2000 \
        | python3 -c 'import json, sys; print(json.dumps({"kind": "save_failed", "error": sys.stdin.read()}))' \
        | post || echo "gaia-hook: reporting the failed save to GAIA failed" >&2
fi

printf '%s' "$payload" | post || echo "gaia-hook: relaying the event to GAIA failed" >&2
exit 0
