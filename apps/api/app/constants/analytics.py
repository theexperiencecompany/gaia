"""Registry keys shared by the analytics wiring and the modules that read it."""

#: The lazy-provider registry key of the shared PostHog client. Lives here, not
#: in app.config.posthog, so a module the embedding sidecar imports can name it
#: without loading the settings that config module validates on import.
POSTHOG_PROVIDER_KEY = "posthog"

#: Person property carrying a user's choice for a user-facing flag, suffixed
#: with the lowercased flag key (feature_browser_obscura), so any metric splits by it.
FEATURE_CHOICE_PERSON_PROPERTY_PREFIX = "feature_"

#: Request header carrying the browser's PostHog session id (set by the web API
#: client), so server events join the session and replay of the click behind them.
POSTHOG_SESSION_HEADER = "X-PostHog-Session-Id"

#: Redis key prefix of capture_once's at-most-once-per-window claim.
ANALYTICS_ONCE_KEY_PREFIX = "analytics:once:"

#: One paywall:blocked per user and gated route per hour: a page load hits ~5 gated routes and a reload repeats them.
PAYWALL_BLOCKED_WINDOW_SECONDS = 3600
