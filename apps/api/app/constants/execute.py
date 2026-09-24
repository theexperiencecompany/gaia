"""Constants for the execute proxy — the single tool that runs integration tools.

EXECUTE_TOOL_NAME is read by the tool itself, the HIL unwrap, the streaming
formatter and the analytics dedupe — one constant so the five sites cannot
drift (root CLAUDE.md, Type Safety item 18).
"""

EXECUTE_TOOL_NAME = "execute"

# Ticket operations ride the execute proxy under reserved inner names (no
# bound tool, no schema); reserved here so no provider tool can squat on them —
# dispatch routes them before resolution, which refuses them outright.
TICKET_APPROVE_NAME = "approve"
TICKET_REVOKE_NAME = "revoke"
TICKET_NAMES = frozenset({TICKET_APPROVE_NAME, TICKET_REVOKE_NAME})

# The args have their own budget inside the doc cap: an oversized schema sheds
# description text, then nested depth, rather than eating the doc. Args must
# render inline for the model.
ARGS_SCHEMA_MAX_CHARS = 3000
# A doc is context the model re-pays for on every later turn, so each section
# is budgeted. Discovery docs inline the return shape up to this size (93% of
# 1074 sampled Composio shapes fit), so a script can be written from the doc.
RETURNS_INLINE_MAX_CHARS = 1000
# The get_tool_schema tool's return-shape bound: full depth for almost every
# tool, degrading by depth for the rare monster schema.
TOOL_SCHEMA_RETURNS_MAX_CHARS = 4000

# Keys under which a tool's metadata may carry a provider-supplied response
# schema. Rendered only when present — most tools do not document their output.
RESPONSE_SCHEMA_METADATA_KEYS = ("output_parameters", "response_schema", "outputSchema")

# Code mode (bash-driven): where the stdlib gaia client is seeded and the
# layered limits that stand in for an approval gate.
# GAIA's dot-dir in the sandbox workspace: persistent under JuiceFS, else ephemeral.
SANDBOX_CLIENT_DIR = "/workspace/.gaia"
# Token TTL is the bash command's timeout plus this buffer, so the token never
# outlives the run by more than a minute.
SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS = 60
# How far the in-sandbox client's HTTP timeout sits ABOVE the host's bound: the
# host must give up first (structured "may or may not have completed" error),
# else a client that quits first has its retry duplicate a mutation still applying.
SANDBOX_EXECUTE_CLIENT_TIMEOUT_BUFFER_SECONDS = 30
# A forged token names whose tools the host runs, so the signing secret's
# length is the whole strength of that claim. Enforced at startup by the
# settings validator, never at mint time.
SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS = 32
# Server-side blast-radius bounds per token (enforced on the callback route):
# a runaway or injected script hits a hard wall instead of unlimited calls.
SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN = 300
SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE = 60
# Budget counters must outlive any legal token; bash caps command timeouts well
# under this, so a counter can never expire while its token is still valid.
SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS = 3600

# The resolver's catalog lookup is on the tool-call critical path (the HIL gate
# resolves a name before the call runs), so the round trip is bounded — a
# degraded Composio fails one call instead of stalling the turn.
COMPOSIO_CATALOG_LOOKUP_TIMEOUT_SECONDS = 15
# A miss is remembered so a hallucinated ALLCAPS name does not re-fetch on every
# gate check and replay; cleared wholesale at the cap (typos, not a working set).
UNKNOWN_CATALOG_SLUG_CACHE_MAX = 512

# Shape-store scopes: catalog tools are user-agnostic so shapes are shared; MCP
# tools are scoped by integration so a private server's shapes never cross users
# (a published MCP shares one integration doc, so subscribers share the scope).
GLOBAL_SHAPE_SCOPE = "global"
MCP_SHAPE_SCOPE_PREFIX = "mcp:"

# Observed-shape learning (services/tool_shape_service.py): structure inferred
# from real dispatch outputs. Arrays are sampled; a dict too wide or with
# non-identifier keys becomes a map, so values (emails, ids) never become keys.
TOOL_SHAPE_ARRAY_SAMPLE = 5
TOOL_SHAPE_MAX_KEYS_PER_OBJECT = 25
TOOL_SHAPE_MAX_CHARS = 20000

# On-demand tool docs inside the sandbox: gaia.schema() caches fetched docs one
# file per tool. Files are disposable TTL caches of the host-side store; global
# docs move to a shared _system overlay once the E2B/JuiceFS mount is reliable.
SANDBOX_TOOL_DOCS_DIR = f"{SANDBOX_CLIENT_DIR}/tools"
SANDBOX_SCHEMA_CACHE_TTL_SECONDS = 900
