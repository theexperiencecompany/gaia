"""Registry keys shared by the analytics wiring and the modules that read it."""

from zoneinfo import ZoneInfo

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

#: The PostHog project's timezone, so an analytics day here is a day on every tile.
ANALYTICS_DAY_TIMEZONE = ZoneInfo("Asia/Kolkata")

#: Redis key prefix of the SET NX gate an at-most-once event passes, by event uuid.
AT_MOST_ONCE_KEY_PREFIX = "analytics:once:"

#: Task name of a gated at-most-once send, so its outcome can be awaited by name.
AT_MOST_ONCE_TASK_NAME = "analytics_send_once"
