"""Constants for the conversation artifact registry and per-turn forwarder."""

# Mirrors GET /api/v1/sessions/{conv_id}/artifacts/{path}; single source of
# truth for the save-time relative->absolute rewrite and the agent-facing session banner.
ARTIFACT_URL_PATH_TEMPLATE = "/api/v1/sessions/{conversation_id}/artifacts"
