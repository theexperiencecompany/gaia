#!/usr/bin/env bash
# Sends a deploy-pipeline Discord notification as a single webhook embed.
#
# Replaces appleboy/discord-action for every deploy notification. That action
# reads the message through a StringSlice env parse (urfave/cli splits env
# values on commas) and, when `color` is set, sends each fragment as an embed
# *title* — Discord caps embed titles at 256 chars, so any long message gets a
# 400 and any comma fragments the message into multiple embeds. An embed
# *description* (4096-char cap) carries rich multi-line messages intact.
#
# Inputs (env):
#   DISCORD_WEBHOOK  webhook URL (required)
#   MESSAGE          message body, markdown allowed (required)
#   COLOR            embed color as hex, e.g. "#ff6b6b" (required)
#   USERNAME         webhook display name (default: Gaia Deploy Bot)
set -euo pipefail

: "${DISCORD_WEBHOOK:?DISCORD_WEBHOOK is required}"
: "${MESSAGE:?MESSAGE is required}"
: "${COLOR:?COLOR is required}"
USERNAME="${USERNAME:-Gaia Deploy Bot}"

# Always log the full message first, so the run itself records what was (or
# failed to be) delivered even when the webhook call is lost.
echo "Discord notification:"
printf '%s\n' "$MESSAGE"

color_int=$((16#${COLOR#\#}))

# Discord caps embed descriptions at 4096 chars — truncate instead of 400ing.
message="$MESSAGE"
if [[ "${#message}" -gt 4000 ]]; then
  message="${message:0:4000}"$'\n'"…(truncated)"
fi

payload=$(jq -n --arg u "$USERNAME" --arg d "$message" --argjson c "$color_int" \
  '{username: $u, embeds: [{description: $d, color: $c}]}')

response_file=$(mktemp)
trap 'rm -f "$response_file"' EXIT

# Bounded: a stuck DNS lookup or socket must not hold a deploy workflow
# hostage for a notification that is non-blocking by design.
status=$(curl -sS --connect-timeout 5 --max-time 20 -o "$response_file" -w '%{http_code}' \
  -H 'Content-Type: application/json' -d "$payload" "$DISCORD_WEBHOOK")

if [[ "$status" -lt 200 || "$status" -ge 300 ]]; then
  echo "::error::Discord webhook returned HTTP $status: $(cat "$response_file")"
  exit 1
fi
echo "notify-discord: OK (HTTP $status)"
