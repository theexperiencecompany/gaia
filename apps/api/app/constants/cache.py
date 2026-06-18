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
OAUTH_STATE_TTL = TEN_MINUTES_TTL
OAUTH_DISCOVERY_TTL = ONE_DAY_TTL
MCP_TOOLS_CACHE_TTL = ONE_DAY_TTL
GLOBAL_TOOLS_CACHE_TTL = SIX_HOUR_TTL
USER_SKILLS_CACHE_TTL = TWELVE_HOUR_TTL
SKILLS_TEXT_CACHE_TTL = TWELVE_HOUR_TTL
INTEGRATION_INSTRUCTIONS_CACHE_TTL = ONE_DAY_TTL
COMMUNITY_CACHE_TTL = FIVE_MINUTES_TTL
FAVICON_CACHE_TTL = SIX_MONTH_TTL
SEARCH_CACHE_TTL = ONE_DAY_TTL
STREAM_TTL = FIVE_MINUTES_TTL
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

# Cache key prefixes
TEAM_CACHE_PREFIX = "team"
CUSTOM_INT_METADATA_CACHE_PREFIX = "custom_int_metadata"
HANDOFF_METADATA_CACHE_PREFIX = "handoff_metadata"
SUBAGENT_CACHE_PREFIX = "subagent_info"
OAUTH_STATE_PREFIX = "mcp_oauth_state"
OAUTH_EXCLUDED_SCOPES_PREFIX = "mcp_oauth_excluded_scopes"
# v2: discovery is now cached as the OAuthDiscovery model (model_dump) rather
# than the old ad-hoc dict; bump busts stale dict-shaped entries.
OAUTH_DISCOVERY_PREFIX = "mcp_oauth_discovery_v2"
OAUTH_STATUS_KEY = "OAUTH_STATUS"
MCP_TOOLS_CACHE_KEY = "mcp:tools:all"
GLOBAL_TOOLS_CACHE_KEY = "tools:global"
USER_SKILLS_CACHE_KEY = "skills:user:{user_id}:agent:{agent_name}"
# v2: the listing now merges in-memory builtin skills; bump busts stale empty entries.
SKILLS_TEXT_CACHE_KEY = "skills:text:v2:{user_id}:{agent_name}"
INTEGRATION_INSTRUCTIONS_CACHE_KEY = "integration_instructions:{user_id}"
STREAM_CHANNEL_PREFIX = "stream:channel:"
STREAM_SIGNAL_PREFIX = "stream:signal:"
STREAM_PROGRESS_PREFIX = "stream:progress:"
STATE_KEY_PREFIX = "oauth_state"
# Single-use marker for login-free integration-connect links (keyed by jti).
CONNECT_LINK_USED_PREFIX = "connect_link_used"
PLATFORM_LINK_TOKEN_PREFIX = "platform_link_token"  # nosec B105
PLATFORM_LINK_TOKEN_TTL = TEN_MINUTES_TTL
# Desktop tool bridge — request ownership keys + per-request result channels.
# A request key expiring means the desktop never answered; the result endpoint
# rejects late POSTs whose key is gone.
DESKTOP_REQUEST_PREFIX = "desktop:request:"
DESKTOP_RESULT_CHANNEL_PREFIX = "desktop:result:"
# The ownership key's TTL is derived per-call from the awaiting tool's timeout
# plus this grace, so the key always outlives the wait (a fixed TTL could be
# outrun by a longer custom timeout, expiring mid-wait and dropping a valid
# late result). The tool deletes the key as soon as it resolves, so this TTL
# only bounds the orphaned-on-crash case.
DESKTOP_REQUEST_TTL_GRACE_SECONDS = 15
EXECUTOR_BUSY_PREFIX = "executor:busy:"
EXECUTOR_BUSY_TTL = THIRTY_MINUTES_TTL
EXECUTOR_QUEUE_PREFIX = "executor:queue:"
EXECUTOR_QUEUE_TTL = ONE_HOUR_TTL  # Tasks expire if not picked up within 1 hour
# Max time a caller waits for a detached executor to finish before draining
# whatever tool events were collected. Matches the busy lock TTL — the executor
# cannot outlive its lock, so waiting longer would be pointless.
EXECUTOR_WAIT_TIMEOUT = THIRTY_MINUTES_TTL
