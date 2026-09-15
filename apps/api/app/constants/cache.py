"""
Cache Constants.

Centralized cache-related constants including TTL values and key prefixes.
Import these instead of defining local constants in services.
"""

# TTL values (in seconds)
ONE_YEAR_TTL = 31_536_000
SIX_MONTH_TTL = 15_552_000
ONE_DAY_TTL = 86_400
TWELVE_HOUR_TTL = 43_200
SIX_HOUR_TTL = 21_600
ONE_HOUR_TTL = 3_600
THIRTY_MINUTES_TTL = 1_800
TEN_MINUTES_TTL = 600
FIVE_MINUTES_TTL = 300


# TTL Aliases
DEFAULT_CACHE_TTL = ONE_HOUR_TTL
STATS_CACHE_TTL = THIRTY_MINUTES_TTL
CUSTOM_INT_METADATA_TTL = ONE_HOUR_TTL
SUBAGENT_CACHE_TTL = ONE_HOUR_TTL
# Subscription plan tier, cached for hot paths (rate limiting, per-request model
# routing). Eventually consistent: a plan change takes effect within the TTL.
SUBSCRIPTION_PLAN_CACHE_PREFIX = "subscription:"
SUBSCRIPTION_PLAN_CACHE_TTL = FIVE_MINUTES_TTL
# The plan catalogue itself, keyed by whether inactive plans are included. Seeded
# by scripts/payment_setup.py, which drops every key after writing.
ACTIVE_PLANS_CACHE_KEY = "plans:active"
ALL_PLANS_CACHE_KEY = "plans:all"
PLANS_CACHE_KEYS = (ACTIVE_PLANS_CACHE_KEY, ALL_PLANS_CACHE_KEY)
# The result page retries payment verification 8 times over ~50s
# (verifyPaymentWithRetry.ts); this TTL covers that window so each retry
# doesn't re-ask Dodo about every session. Minting a new session drops the key.
CHECKOUT_SCAN_MISS_CACHE_PREFIX = "checkout_scan_miss:"
CHECKOUT_SCAN_MISS_TTL = 60
# The tracked-todo summary injected into comms context. Deliberately short-TTL:
# the list changes as the agent works, and a stale pin is worse than the lookup
# it saves. Keyed by user alone, so only the unpinned summary may use it.
TRACKED_TODOS_SUMMARY_CACHE_KEY = "tracked_todos:summary:{user_id}"
TRACKED_TODOS_SUMMARY_CACHE_TTL = 60
OAUTH_STATE_TTL = TEN_MINUTES_TTL
OAUTH_DISCOVERY_TTL = ONE_DAY_TTL
MCP_TOOLS_CACHE_TTL = ONE_DAY_TTL
USER_SKILLS_CACHE_TTL = TWELVE_HOUR_TTL
SKILLS_TEXT_CACHE_TTL = TWELVE_HOUR_TTL
INTEGRATION_INSTRUCTIONS_CACHE_TTL = ONE_DAY_TTL
COMMUNITY_CACHE_TTL = FIVE_MINUTES_TTL
FAVICON_CACHE_TTL = SIX_MONTH_TTL
SEARCH_CACHE_TTL = ONE_DAY_TTL
STREAM_TTL = FIVE_MINUTES_TTL
# A streaming turn refreshes its progress/resume keys once they drop below this,
# so the refresh costs one TTL read per frame instead of a read-plus-two-writes.
STREAM_LIVENESS_REFRESH_AFTER = STREAM_TTL // 2
STATE_TOKEN_TTL = TEN_MINUTES_TTL
MOBILE_REDIRECT_TTL = FIVE_MINUTES_TTL

# Long TTLs with event-driven invalidation — short TTLs are a symptom of
# missing invalidation, not a safety net.
INTEGRATION_STATUS_CACHE_TTL = ONE_DAY_TTL
SUBAGENT_PROMPT_CACHE_TTL = ONE_DAY_TTL
PROVIDER_METADATA_CACHE_TTL = ONE_DAY_TTL
WEB_SEARCH_CACHE_TTL = TEN_MINUTES_TTL
WEBPAGE_FETCH_CACHE_TTL = THIRTY_MINUTES_TTL
WORKFLOW_GENERATION_CACHE_TTL = ONE_DAY_TTL

# Bounded in-process LRU+TTL cache for per-(integration, user) compiled
# subagent graphs. Caps RSS growth that scales with MAU × MCP integrations.
SUBAGENT_GRAPH_CACHE_MAX_SIZE = 100
SUBAGENT_GRAPH_CACHE_TTL_SECONDS = TEN_MINUTES_TTL
SUBAGENT_GRAPH_CLEANUP_INTERVAL_SECONDS = 60

# Repository layer aliases: entity rows are hot/long-lived; query caches are
# shorter (fan out per argument set). The generation counter, not the TTL,
# actually invalidates them — these bounds only cap worst-case staleness.
REPO_ENTITY_TTL = ONE_DAY_TTL
REPO_QUERY_TTL = ONE_HOUR_TTL
# Scope segment for non-user-scoped (global) repositories.
REPO_GLOBAL_SCOPE = "global"
# Debounce window for UserRepository.touch_last_active — one write per user per
# minute (Redis SET NX EX gate), so per-request auth never storms Mongo.
LAST_ACTIVE_DEBOUNCE_SECONDS = 60

# Per-repository cache-key prefixes (one namespace per domain).
NOTE_CACHE_PREFIX = "note"
TODO_CACHE_PREFIX = "todo"
PROJECT_CACHE_PREFIX = "project"
USER_CACHE_PREFIX = "user"
# Redis SET NX EX gate that debounces UserRepository.touch_last_active.
LAST_ACTIVE_GATE_PREFIX = "last_active_gate"

# Cache key prefixes
TEAM_CACHE_PREFIX = "team"
CUSTOM_INT_METADATA_CACHE_PREFIX = "custom_int_metadata"
HANDOFF_METADATA_CACHE_PREFIX = "handoff_metadata"
# Custom-MCP display name resolved for handoff (keyed by integration id).
HANDOFF_NAME_CACHE_PREFIX = "handoff_name"
SUBAGENT_CACHE_PREFIX = "subagent_info"
OAUTH_STATE_PREFIX = "mcp_oauth_state"
OAUTH_EXCLUDED_SCOPES_PREFIX = "mcp_oauth_excluded_scopes"
# v2: discovery is now cached as the OAuthDiscovery model (model_dump) rather
# than the old ad-hoc dict; bump busts stale dict-shaped entries.
OAUTH_DISCOVERY_PREFIX = "mcp_oauth_discovery_v2"
OAUTH_STATUS_KEY = "OAUTH_STATUS"

# Every cache derived from a user's integration set; ALL must be busted
# together on any change or the views diverge (a stale OAUTH_STATUS once hid a
# freshly-connected MCP). `{user_id}` is substituted by CacheInvalidator at call time.
USER_INTEGRATION_CACHE_PATTERNS = [
    "tools:user:{user_id}:*",
    "tool_namespaces:{user_id}",
    f"{OAUTH_STATUS_KEY}:{{user_id}}",
]
MCP_TOOLS_CACHE_KEY = "mcp:tools:all"
USER_SKILLS_CACHE_KEY = "skills:user:{user_id}:agent:{agent_name}"
# v2: the listing now merges in-memory builtin skills; bump busts stale empty entries.
SKILLS_TEXT_CACHE_KEY = "skills:text:v2:{user_id}:{agent_name}"
INTEGRATION_INSTRUCTIONS_CACHE_KEY = "integration_instructions:{user_id}"
# Conversation-level artifact registry; long TTL with event-driven invalidation
# on every upsert/remove — a chat turn reads it once instead of re-scanning the costly JuiceFS dir.
CONV_ARTIFACTS_CACHE_PATTERN = "conv_artifacts:{user_id}:{conv_id}"
# A user's uploaded-file listings; busted on every file upload/update/delete.
FILES_CACHE_PATTERN = "files:{user_id}:*"
STREAM_SIGNAL_PREFIX = "stream:signal:"
STREAM_PROGRESS_PREFIX = "stream:progress:"
# Replayable per-stream event log (Redis Stream). Entry ids double as SSE ids,
# so any subscriber can attach late or reconnect with Last-Event-ID and replay.
STREAM_EVENTS_PREFIX = "stream:events:"
STREAM_EVENTS_MAXLEN = 4096
# Reverse index {user_id}:{conversation_id} -> stream_id for the in-flight chat
# turn, so a reloaded client can rediscover and re-attach to a live stream.
STREAM_ACTIVE_PREFIX = "stream:active:"
# Turn-send dedup: {user_id}:{turn_id} -> stream_id, claimed atomically (SETNX)
# so a retried POST can't persist the same turn twice.
STREAM_TURN_DEDUP_PREFIX = "stream:turn:"
STREAM_TURN_DEDUP_TTL = TEN_MINUTES_TTL
STATE_KEY_PREFIX = "oauth_state"
# Single-use login-free integration-connect codes: code -> {user_id, integration_id}.
CONNECT_LINK_PREFIX = "connect_link"
PLATFORM_LINK_TOKEN_PREFIX = "platform_link_token"  # nosec B105
PLATFORM_LINK_TOKEN_TTL = TEN_MINUTES_TTL
# Opposite direction to the token above: the WEB mints this at the
# platform-pick step, the BOT redeems it on first contact. code -> {user_id, first_message}.
PLATFORM_LINK_CODE_PREFIX = "platform_link_code"  # nosec B105
PLATFORM_LINK_CODE_TTL = THIRTY_MINUTES_TTL
# Held for one redemption, not for the code's life: it makes a redemption
# single-use while the record survives a refusal. The TTL is the recovery bound —
# a redeemer that died mid-link frees the code again once it lapses.
PLATFORM_LINK_CODE_CLAIM_TTL = FIVE_MINUTES_TTL
# Desktop tool bridge — request ownership keys + per-request result channels.
# A request key expiring means the desktop never answered; the result endpoint
# rejects late POSTs whose key is gone.
DESKTOP_REQUEST_PREFIX = "desktop:request:"
DESKTOP_RESULT_CHANNEL_PREFIX = "desktop:result:"
# Latest desktop (Electron) release resolved from GitHub for the download page.
# Infrequent releases, so 30 min keeps the page fresh without hammering GitHub.
DESKTOP_RELEASE_CACHE_KEY = "desktop:release:latest"
DESKTOP_RELEASE_CACHE_TTL = THIRTY_MINUTES_TTL
# The ownership key's TTL is derived per-call from the awaiting tool's timeout
# plus this grace, so it always outlives the wait. The tool deletes the key as
# soon as it resolves, so this only bounds the orphaned-on-crash case.
DESKTOP_REQUEST_TTL_GRACE_SECONDS = 15
# Remembers a declined call for the rest of the turn (keyed by stream_id) so a
# retrying agent is auto-denied instead of re-prompting the user for the same
# action.
HIL_DECLINED_PREFIX = "hil:declined:"
# One workflow's "out of runs / budget" notice, keyed by user+workflow. The
# daily wall it reports is worth exactly one message, not one per fire (a production thread ran to six).
WORKFLOW_LIMIT_NOTICE_PREFIX = "workflow:limit-notice:"
WORKFLOW_LIMIT_NOTICE_TTL = ONE_DAY_TTL

# One bot user's personalised Dodo upgrade link; gates the MINT, not the
# message, so a lapsed user's blocked turns don't each cost a get_plans call
# and a checkout_sessions insert. An hour, not a day, since a Dodo session is single-use.
BOT_UPGRADE_LINK_PREFIX = "bot:upgrade-link:"
BOT_UPGRADE_LINK_TTL = ONE_HOUR_TTL

EXECUTOR_BUSY_PREFIX = "executor:busy:"
EXECUTOR_BUSY_TTL = THIRTY_MINUTES_TTL
EXECUTOR_QUEUE_PREFIX = "executor:queue:"
EXECUTOR_QUEUE_TTL = ONE_HOUR_TTL  # Tasks expire if not picked up within 1 hour
# Max time a caller waits for a detached executor to finish before draining
# whatever tool events were collected. Matches the busy lock TTL — the executor
# cannot outlive its lock, so waiting longer would be pointless.
EXECUTOR_WAIT_TIMEOUT = THIRTY_MINUTES_TTL
#: Shorter than the worker's job timeout on purpose: waiting as long as the job
#: means the job gets cut first mid-bookkeeping. Seen live: a stopped-mid-run
#: executor left a record stuck 'running'.
BACKGROUND_EXECUTOR_WAIT_TIMEOUT = 25 * 60
# ElevenLabs voice lists (account + shared library) cached for the voice picker.
ELEVENLABS_VOICES_CACHE_KEY = "voice:elevenlabs_voices"
ELEVENLABS_SHARED_VOICES_CACHE_KEY = "voice:elevenlabs_shared_voices"
# Upper bound a voice-mode stream waits for a delegated executor's narrated
# answer before sending [DONE] anyway. Real action turns resolve in a few
# seconds; on timeout the answer still reaches the user via the WebSocket push.
VOICE_EXECUTOR_RESULT_TIMEOUT_S = 90.0

# One-shot gate (SET NX) for the "priority compute used this month" in-app notice,
# so a degraded pro user is told once per month, not once per turn.
COST_BUDGET_NOTIFIED_KEY = "cost_budget_notified:{user_id}:{window}"

# Keyed by user plus a hash of the answers it was written from, so a changed
# Q1/Q2 answer reads a never-written key rather than a stale question. Two
# hours covers a wizard someone walked away from before pressing completion.
FIRST_QUESTION_CACHE_PREFIX = "onboarding:first_question:"
FIRST_QUESTION_CACHE_TTL = 2 * ONE_HOUR_TTL
#: Prefix of the tiered rate limiter's per-user counters: ``{prefix}:{user_id}:{feature}:{period}:{window}``.
#: Named so a dev tool can clear one user's counters without knowing the rest of the key.
RATE_LIMIT_KEY_PREFIX = "rate_limit"
