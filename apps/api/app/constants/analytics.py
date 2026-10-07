"""Registry keys shared by the analytics wiring and the modules that read it."""

#: The lazy-provider registry key of the shared PostHog client. Lives here, not
#: in app.config.posthog, so a module the embedding sidecar imports can name it
#: without loading the settings that config module validates on import.
POSTHOG_PROVIDER_KEY = "posthog"

#: Person property carrying a user's choice for a user-facing flag, suffixed
#: with the lowercased flag key (feature_browser_obscura), so any metric splits by it.
FEATURE_CHOICE_PERSON_PROPERTY_PREFIX = "feature_"
