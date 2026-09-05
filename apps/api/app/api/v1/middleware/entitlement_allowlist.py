"""The single list of paths that stay free when the paywall is deny-by-default.

``EntitlementMiddleware`` blocks every authenticated request whose caller is not
on PRO. That is only safe because the handful of surfaces a lapsed user still
needs — to see who they are, to pay, to log out, to let a provider call us back —
are enumerated here and nowhere else. A second copy of this list would drift and
silently open a paid surface, which is the exact bug the middleware exists to
prevent.

Matching is a plain ``startswith`` on ``request.url.path``, so an entry gates a
whole subtree. Keep entries as specific as the surface actually needs: every
extra character is a route that can never be monetised.
"""

# Ordered roughly by "why is this free": infrastructure, auth, payment, public,
# self-authenticating callbacks. Each entry carries the reason it must stay open.
FREE_PATH_PREFIXES: tuple[str, ...] = (
    # ── Infrastructure / observability ──────────────────────────────────────
    "/health",  # liveness probe — Swarm restarts the task if this 402s
    "/ping",  # readiness probe, same reason
    "/metrics",  # Prometheus scrape; the scraper has no user session at all
    "/docs",  # Swagger UI (covers /docs/oauth2-redirect)
    "/redoc",  # ReDoc UI
    "/openapi.json",  # schema both doc UIs fetch
    "/static",  # mounted static assets (favicons, email images)
    "/api/v1/ping",  # v1-prefixed readiness probe
    # ── Identity: a lapsed user must still be able to see who they are ─────
    # The web shell renders the paywall modal *inside* the authenticated
    # layout, so it needs the session user before it can show the wall. A 402
    # here would loop: paywall opens -> layout refetches -> 402 -> paywall.
    "/api/v1/user/me",  # GET (session bootstrap) + PATCH (profile)
    "/api/v1/user/name",  # profile chores: no spend, and the wall shows the name
    "/api/v1/user/timezone",  # the wall and receipts render in the user's zone
    "/api/v1/user/logout",  # a lapsed user must be able to leave
    "/api/v1/oauth",  # login redirects + provider callbacks (no session yet)
    "/api/v1/dev/",  # dev-only identity router; mounted only in development
    # ── Payment: the way out of the paywall cannot itself be paywalled ─────
    "/api/v1/payments",  # plans, checkout-session, verify, status, cancel,
    #                      and webhooks/dodo (Dodo calls it with no session)
    # ── Onboarding: runs before the first subscription exists ──────────────
    "/api/v1/onboarding",  # status/phase/preferences drive the pre-pay flow
    # ── Public marketing surfaces (no session required) ────────────────────
    "/api/v1/blogs",  # public blog content on the marketing site
    "/api/v1/desktop/releases",  # public download lookup for the landing page
    # ── Support: a blocked user must be able to tell us they are blocked ───
    "/api/v1/support",  # request submission + its rate-limit status
    # ── Self-authenticating callbacks and bridges (no user session) ────────
    "/api/v1/bot",  # internal bot API-key router. Its two spend-incurring
    #                 turns gate themselves per turn against the *linked*
    #                 user (bot.py `_bot_stream_entitlement_gate` and the
    #                 `require_active_subscription` call in bot_transcribe);
    #                 the rest are linking/admin. WorkOSAuthMiddleware also
    #                 excludes this prefix, so request.state.user is never
    #                 populated here and the middleware could not gate it.
    "/api/v1/webhook",  # Composio provider webhook, signature-authenticated
    "/api/v1/platform-auth",  # Discord/Slack OAuth callbacks, no session
    "/api/v1/notifications/unsubscribe",  # HMAC-signed one-click unsubscribe
    "/api/v1/integrations/connect-link",  # login-free single-use connect code
    "/api/v1/device/pair/start",  # device daemon pairing — authenticates with
    "/api/v1/device/pair/poll",  # the pairing code, not a user session
    "/api/v1/device/token",  # refresh-credential exchange
    "/api/v1/device/servers",  # device connect JWT, checked in-handler
)


def is_free_path(path: str) -> bool:
    """Whether ``path`` is exempt from the paid-only gate."""
    return path.startswith(FREE_PATH_PREFIXES)
