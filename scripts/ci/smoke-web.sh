#!/usr/bin/env bash
# smoke-web.sh — post-deploy smoke audit for the Cloudflare web deploy.
#
# Subcommands:
#   prod                        Curl the sample URL list against production and
#                               assert what the 2026-10-17 verification observed:
#                               200 (404 for the bogus slug), a self-referencing
#                               canonical link, a full hreflang cluster on
#                               localized pages, x-opennext-cache: HIT on a
#                               repeat request, and NO X-Robots-Tag noindex
#                               anywhere (the preview-noindex guard must never
#                               leak to prod).
#
# Post-deploy alerting only: this runs as its own deploy-web.yml job behind
# the deploy, so a red smoke never blocks or rolls back a deploy. Fail loud.
#
# Convention: one command line per workflow step — the logic lives here, the
# step calls `bash scripts/ci/smoke-web.sh prod`. Env contract: SMOKE_BASE_URL
# overrides the default https://heygaia.io (tests point it at a stub).

set -euo pipefail
# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

cmd_prod() {
  python3 - "${BASE_URL:-https://heygaia.io}" <<'EOF'
import re
import sys
import urllib.request

base = sys.argv[1].rstrip("/")

PAGES = [
    "/learn/ical",
    "/compare/hey-email",
    "/automate/slack-teams",
    "/alternative-to/airtable",
    "/de/learn/ical",
    "/pt-BR/compare/lark",
]
MARKETPLACE = "/marketplace/super-productivity"
BOGUS = "/compare/no-such-tool-zzz"

failures: list[str] = []


def get(path: str) -> tuple[int, dict[str, str], str]:
    req = urllib.request.Request(base + path, headers={"User-Agent": "gaia-smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, headers, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, headers, body


def check(condition: bool, message: str) -> None:
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        failures.append(message)


for page in PAGES:
    status, headers, body = get(page)
    check(status == 200, f"{page} status is 200 (got {status})")
    if status != 200:
        continue
    canonical = re.findall(r'<link rel="canonical" href="([^"]+)"', body)
    check(canonical == [base + page], f"{page} self-referencing canonical (got {canonical})")
    hreflangs = re.findall(r'hrefLang="([^"]+)"', body)
    check(
        len(hreflangs) >= 7 and "x-default" in hreflangs,
        f"{page} hreflang cluster present ({len(hreflangs)} alternates)",
    )
    check(
        "noindex" not in headers.get("x-robots-tag", ""),
        f"{page} carries no noindex header",
    )

status, _headers, _body = get(MARKETPLACE)
# The marketplace [slug] page is client-rendered (no SSR canonical/hreflang to
# assert and no static 404 for unknown slugs), so reachability is the check.
check(status == 200, f"{MARKETPLACE} status is 200 (got {status})")

status, _headers, _body = get(BOGUS)
check(status == 404, f"{BOGUS} status is 404 (got {status})")

# Edge-cache proof: an immediate repeat request for a prerendered page must
# come from the OpenNext incremental cache. Observed in prod 2026-10-17 as
# `x-opennext-cache: HIT` alongside `x-nextjs-prerender: 1`.
_status, headers, _body = get("/learn/ical")
check(
    headers.get("x-opennext-cache") == "HIT",
    f"repeat /learn/ical served from cache (x-opennext-cache={headers.get('x-opennext-cache')!r})",
)

if failures:
    print(f"smoke-web: FAIL — {len(failures)} failing check(s)")
    sys.exit(1)
print("smoke-web: OK (all post-deploy checks pass)")
EOF
}

main() {
  case "${1:-}" in
    prod) cmd_prod ;;
    *) echo "usage: $0 prod" >&2; exit 2 ;;
  esac
}

main "$@"
