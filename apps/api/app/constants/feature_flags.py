"""Error copy the user-facing feature flag routes send in their envelopes."""

FEATURE_NOT_FOUND_MESSAGE = "Feature not found"
FEATURE_NOT_FOUND_WHY = "no user-facing feature flag has this key"
FEATURE_NOT_FOUND_FIX = "List the toggleable features with GET /api/v1/features"

FEATURE_KILLED_MESSAGE = "This feature is paused for everyone right now"
FEATURE_KILLED_WHY = "the flag's kill switch is engaged in PostHog, which overrides every choice"
FEATURE_KILLED_FIX = "Try again once the feature is back; your current choice is kept"

FEATURE_USER_NOT_FOUND_MESSAGE = "User not found"
FEATURE_USER_NOT_FOUND_WHY = "no user document matches the authenticated session's id"
