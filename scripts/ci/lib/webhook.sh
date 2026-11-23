#!/usr/bin/env bash
# webhook.sh — the one way a CI script posts JSON to a Discord or Slack webhook.
#
#   post_webhook <name> <url> <json payload>   prints the response body; returns
#                                              non-zero (with an ::error) on a
#                                              non-2xx reply or a dead socket.
#
# deploy.sh notify sources it; analytics.py csp-soak runs it through bash, so a
# Python entrypoint posts exactly as the deploy messages do.
#
# Sourced, never executed: it defines a function, nothing else.

post_webhook() {
  local name="$1" url="$2" payload="$3" response_file status
  response_file=$(mktemp)
  # Bounded: a stuck DNS lookup or socket must not hold a workflow hostage for
  # a notification.
  status=$(curl -sS --connect-timeout 5 --max-time 20 -o "$response_file" -w '%{http_code}' \
    -H 'Content-Type: application/json' -d "$payload" "$url") || status=000
  if [[ "$status" -lt 200 || "$status" -ge 300 ]]; then
    echo "::error::$name webhook returned HTTP $status: $(cat "$response_file")" >&2
    rm -f "$response_file"
    return 1
  fi
  cat "$response_file"
  rm -f "$response_file"
}
