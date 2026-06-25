"""Constants for the conversation artifact registry and per-turn forwarder."""

# Fields persisted on each artifact registry element (alongside updated_at / body).
ARTIFACT_ELEMENT_FIELDS = ("path", "size_bytes", "mtime", "content_type")

# Greppable log prefix for the artifact forwarder subsystem.
ARTIFACT_LOG_PREFIX = "[artifacts]"

# Public URL path (under settings.HOST) that serves a conversation's artifacts.
# Mirrors the GET /api/v1/sessions/{conv_id}/artifacts/{path} route. Single
# source of truth for the save-time relative→absolute rewrite and the
# agent-facing session banner. Format with the conversation id.
ARTIFACT_URL_PATH_TEMPLATE = "/api/v1/sessions/{conversation_id}/artifacts"

# The bot message row is written after the forwarder starts, so an artifact
# created early in the turn can arrive before the row exists. Retry briefly to
# bridge that window — the row lands within a few hundred ms.
ARTIFACT_PERSIST_MAX_ATTEMPTS = 5
ARTIFACT_PERSIST_RETRY_BASE_DELAY = 0.1

# JuiceFS default block size: reading in block-sized chunks pulls each block into
# the local cache with no wasted partial fetches.
ARTIFACT_WARM_CHUNK_BYTES = 4 * 1024 * 1024

# Cap concurrent cache-warm reads so an artifact burst in one turn can't saturate
# the shared default thread pool and starve other IO.
ARTIFACT_WARM_MAX_CONCURRENCY = 4
