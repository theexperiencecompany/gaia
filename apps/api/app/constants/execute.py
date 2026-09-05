"""Constants for the execute proxy — the single tool that runs integration tools.

EXECUTE_TOOL_NAME is read by the tool itself, the HIL unwrap, the streaming
formatter and the analytics dedupe — one constant so the five sites cannot
drift (root CLAUDE.md, Type Safety item 18).
"""

EXECUTE_TOOL_NAME = "execute"

# A rendered schema doc becomes conversation context the model re-pays for on
# every later turn, and Composio response schemas alone can run to thousands of
# tokens — cap the doc, never inject a huge schema wholesale.
SCHEMA_DOC_MAX_CHARS = 6000

# The args schema has its own budget inside the doc cap: an oversized schema
# degrades to shallower levels (nested detail collapses to a "..." marker)
# instead of eating the whole doc or being clipped mid-JSON. Args must render
# inline — the model constructs calls from it.
ARGS_SCHEMA_MAX_CHARS = 3000
# The get_tool_schema tool's per-section output bound: full depth for almost
# every tool, degrading by depth for the rare monster schema.
TOOL_SCHEMA_RETURNS_MAX_CHARS = 4000

# Keys under which a tool's metadata may carry a provider-supplied response
# schema. Rendered only when present — most tools do not document their output
# shape, and the doc must not pretend otherwise.
RESPONSE_SCHEMA_METADATA_KEYS = ("output_parameters", "response_schema", "outputSchema")

# Code mode (bash-driven): where the stdlib gaia client is seeded inside the
# sandbox, and the layered limits that stand in for an approval gate. The token
# TTL is the bash command's own timeout plus this buffer, so a call started
# near the deadline still completes but the token never outlives the run by
# more than a minute.
# Inside GAIA's own dot-dir in the sandbox workspace (alongside .gaia/runs,
# .gaia/gaia-tasks): persistent when JuiceFS is mounted, ephemeral otherwise.
SANDBOX_CLIENT_DIR = "/workspace/.gaia"
SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS = 60
# How far the in-sandbox client's HTTP timeout sits ABOVE the host's own bound
# (TOOL_EXECUTION_TIMEOUT_SECONDS). The host must always be the one that gives
# up: it answers a timed-out call with a structured "may or may not have
# completed" error, whereas a client that gives up first abandons a mutation
# the host is still applying — and the script's retry then duplicates it. This
# is also why `bash` is in TOOL_TIMEOUT_EXEMPT_TOOLS: the enclosing bash call
# being cut at the generic bound would kill the script mid-answer.
SANDBOX_EXECUTE_CLIENT_TIMEOUT_BUFFER_SECONDS = 30
# A forged token names whose tools the host runs, so the signing secret's
# length is the whole strength of that claim. Enforced at startup by the
# settings validator, never at mint time — a misconfigured deploy must not
# start.
SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS = 32
# Server-side blast-radius bounds per token (enforced on the callback route):
# a runaway or injected script hits a hard wall instead of unlimited calls.
SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN = 300
SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE = 60
# Budget counters must outlive any legal token; bash caps command timeouts well
# under this, so a counter can never expire while its token is still valid.
SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS = 3600

# The resolver's on-demand catalog lookup is on the tool-call critical path:
# the HIL gate resolves a name before the call is even allowed to run — twice
# per gated call, plus once per sibling in the same AI message. So the round
# trip is bounded (a degraded Composio fails one call instead of stalling the
# whole turn) and a miss is remembered: a hallucinated ALLCAPS name otherwise
# costs a fresh round trip on every gate check and every replay of the
# approvals node. The miss cache is cleared wholesale at its cap — those names
# are model typos, not a working set worth evicting one at a time.
COMPOSIO_CATALOG_LOOKUP_TIMEOUT_SECONDS = 15
UNKNOWN_CATALOG_SLUG_CACHE_MAX = 512

# Shape-store scopes: catalog tools are user-agnostic so their observed shapes
# are shared; MCP tools are scoped by integration so a private server's shapes
# never cross users (a published MCP shares one integration doc, so its
# subscribers share the scope naturally).
GLOBAL_SHAPE_SCOPE = "global"
MCP_SHAPE_SCOPE_PREFIX = "mcp:"

# Observed-shape learning (services/tool_shape_service.py): structure inferred
# from real dispatch outputs. Arrays are sampled, and a dict wider than the key
# threshold — or one whose keys are not identifier-shaped — is treated as a map
# so value-derived keys (emails, labels, ids) do not become schema property
# names. The char cap bounds one tool's stored record.
TOOL_SHAPE_ARRAY_SAMPLE = 5
TOOL_SHAPE_MAX_KEYS_PER_OBJECT = 25
TOOL_SHAPE_MAX_CHARS = 20000

# On-demand tool docs inside the sandbox: gaia.schema() caches fetched docs as
# one file per tool. Files are disposable TTL caches of the host-side store;
# when the E2B<->JuiceFS mount is reliable, global-scope docs move to the
# shared _system overlay and this dir symlinks the common set.
SANDBOX_TOOL_DOCS_DIR = f"{SANDBOX_CLIENT_DIR}/tools"
SANDBOX_SCHEMA_CACHE_TTL_SECONDS = 900
