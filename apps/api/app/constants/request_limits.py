"""App-wide request ceilings per caller, set from production's 14-day per-minute peaks (Loki)."""

#: Signed-in users, per user id: p99.9 50/min, max 51.
SIGNED_IN_USER_PER_MINUTE = 300
#: Signed-out callers, per address: busiest-window max 18/min; webhooks peaked at 23.
ANONYMOUS_VIEWER_PER_MINUTE = 120
#: GAIA's web server, per address presenting INTERNAL_API_TOKEN: max 459/min. Bounds a leaked token.
INTERNAL_SOURCE_PER_MINUTE = 2000
#: Public PDF exports, per address: each uncached one launches a browser.
PUBLIC_PDF_EXPORT_PER_MINUTE = 6
