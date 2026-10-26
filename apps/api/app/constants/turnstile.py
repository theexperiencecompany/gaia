"""Cloudflare Turnstile server-side verification."""

TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Cloudflare answers in well under a second; past this the form fails loud instead of hanging.
TURNSTILE_SITEVERIFY_TIMEOUT_SECONDS = 10.0
