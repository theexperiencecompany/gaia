#!/bin/sh
# Runtime entrypoint for the Next.js web container.
#
# Replaces the build-time placeholder API URL with the real URL derived from
# NEXT_PUBLIC_APP_URL. This lets one image work across multiple PR previews
# on different ports without per-PR rebuilds.
#
# NEXT_PUBLIC_API_BASE_URL is read on the server at render time, so the
# placeholder gets baked into every server-rendered output: client JS, server
# JS, prerendered HTML, RSC flight payloads (including .segment.rsc), and the
# required-server-files.json runtime config. All of these need patching.
set -e

PLACEHOLDER="http://preview.placeholder.buildtime/api/v1/"

if [ -n "${NEXT_PUBLIC_APP_URL:-}" ]; then
  REAL_URL="${NEXT_PUBLIC_APP_URL%/}/api/v1/"

  if [ "${REAL_URL}" != "${PLACEHOLDER}" ]; then
    find /app/apps/web/.next -type f \
      \( -name "*.js" -o -name "*.html" -o -name "*.rsc" -o -name "*.json" \) \
      2>/dev/null \
      | xargs grep -l "${PLACEHOLDER}" 2>/dev/null \
      | xargs -r sed -i "s|${PLACEHOLDER}|${REAL_URL}|g"
  fi
fi

exec node apps/web/server.js
