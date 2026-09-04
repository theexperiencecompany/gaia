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
# The response shape only guides how results are consumed, so it renders inline
# only when small; above this it becomes a one-line pointer to the on-demand
# lookup (gaia.schema / the sandbox tool-docs folder) instead of re-paid
# context on every later turn.
RESPONSE_SCHEMA_INLINE_MAX_CHARS = 1000

# Keys under which a tool's metadata may carry a provider-supplied response
# schema. Rendered only when present — most tools do not document their output
# shape, and the doc must not pretend otherwise.
RESPONSE_SCHEMA_METADATA_KEYS = ("output_parameters", "response_schema", "outputSchema")

# Code mode (bash-driven): where the stdlib gaia client is seeded inside the
# sandbox, and the layered limits that stand in for an approval gate. The token
# TTL is the bash command's own timeout plus this buffer, so a call started
# near the deadline still completes but the token never outlives the run by
# more than a minute.
SANDBOX_CLIENT_DIR = "/tmp/.gaia"  # nosec B108 -- path inside the E2B sandbox, not this host
SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS = 60
# Server-side blast-radius bounds per token (enforced on the callback route):
# a runaway or injected script hits a hard wall instead of unlimited calls.
SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN = 300
SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE = 60
# Budget counters must outlive any legal token; bash caps command timeouts well
# under this, so a counter can never expire while its token is still valid.
SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS = 3600

# Observed-shape learning (services/tool_shape_service.py): structure inferred
# from real dispatch outputs. Arrays are sampled, and a dict wider than the key
# threshold is treated as a map so value-derived keys (emails, ids) never
# become schema property names. The char cap bounds one tool's stored record.
TOOL_SHAPE_ARRAY_SAMPLE = 5
TOOL_SHAPE_MAX_KEYS_PER_OBJECT = 25
TOOL_SHAPE_MAX_CHARS = 20000

# On-demand tool docs inside the sandbox: gaia.schema() caches fetched docs as
# one file per tool. Files are disposable TTL caches of the host-side store
# (single Mongo record per tool, user-agnostic); when the E2B<->JuiceFS mount
# is reliable this dir becomes a symlink to a shared read-only mount.
SANDBOX_TOOL_DOCS_DIR = "/tmp/.gaia/tools"  # nosec B108 -- path inside the E2B sandbox, not this host
SANDBOX_SCHEMA_CACHE_TTL_SECONDS = 900
