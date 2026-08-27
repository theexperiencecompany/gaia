#!/usr/bin/env bash
# disable-cf-builds.sh — best-effort probe/disable for Cloudflare Workers Builds.
# Usage: CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=d65fe... bash scripts/ci/disable-cf-builds.sh
# If a Git-connected Build is found, the script tells you to disconnect it in the dashboard
# (the underlying API is dashboard-only for many accounts and may 404 — that is expected).
set -euo pipefail

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-d65fe47d4d3b4f2725e87b91c772cbc3}"
WORKER_NAME="${WORKER_NAME:-gaia}"
TOKEN="${CLOUDFLARE_API_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "CLOUDFLARE_API_TOKEN not set — cannot query Cloudflare API."
  echo "Set it and re-run, or perform the manual dashboard step:"
  echo "  Workers & Pages → $WORKER_NAME → Settings → Builds → Disconnect / Disable automatic builds"
  echo "See docs/cloudflare-workers-builds.md"
  exit 0
fi

echo "Account: ${ACCOUNT_ID:0:6}…  Worker: $WORKER_NAME"
echo "Probing Cloudflare API (best-effort, 404 is expected if Builds is dashboard-only)…"
echo ""

probe() {
  local path="$1"
  echo "GET $path"
  curl -sS -H "Authorization: Bearer $TOKEN" "https://api.cloudflare.com/client/v4$path" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d, indent=2)[:6000])" 2>&1 | head -n 120 || true
  echo ""
}

# Known / plausible endpoints (any may 404 depending on account plan)
probe "/accounts/${ACCOUNT_ID}/workers/scripts/${WORKER_NAME}"
probe "/accounts/${ACCOUNT_ID}/workers/services/${WORKER_NAME}"
probe "/accounts/${ACCOUNT_ID}/workers/services/${WORKER_NAME}/environments/production"

echo "—"
echo "If any response shows a \"build_config\", \"source\", or \"git\" with a connected repo, disable it:"
echo "  https://dash.cloudflare.com → Workers & Pages → $WORKER_NAME → Settings → Builds → Disconnect"
echo "Docs: https://developers.cloudflare.com/workers/ci-cd/builds/"
echo ""
echo "Also try dashboard API (may require additional token scopes):"
echo "  curl -H \"Authorization: Bearer \$TOKEN\" https://api.cloudflare.com/client/v4/accounts/\$ACCOUNT_ID/workers/builds 2>&1 | head"
echo ""
echo "After disconnecting, pushes to master should trigger ONLY the GitHub workflow Deploy Web (Cloudflare)."
