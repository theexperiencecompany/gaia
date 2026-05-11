#!/bin/sh
# Runtime entrypoint for the Next.js web container.
#
# Replaces the build-time placeholder API URL with the real URL derived from
# NEXT_PUBLIC_APP_URL. This lets one image work across multiple PR previews
# on different ports without per-PR rebuilds.
set -e

PLACEHOLDER="http://preview.placeholder.buildtime/api/v1/"

if [ -n "${NEXT_PUBLIC_APP_URL:-}" ]; then
  REAL_URL="${NEXT_PUBLIC_APP_URL%/}/api/v1/"

  if [ "${REAL_URL}" != "${PLACEHOLDER}" ]; then
    # Replace in both server-side chunks (.next/server) and client-side
    # static chunks (.next/static) produced by the standalone build.
    find /app/apps/web/.next -type f -name "*.js" 2>/dev/null \
      | xargs grep -l "${PLACEHOLDER}" 2>/dev/null \
      | xargs -r sed -i "s|${PLACEHOLDER}|${REAL_URL}|g"
  fi
fi

exec node apps/web/server.js
