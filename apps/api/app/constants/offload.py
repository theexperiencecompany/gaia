"""Constants for the workspace-offload + file-mining flow.

When the compaction middleware offloads a tool's output to a workspace file,
the message carries a structured marker and the agent mines the file with
query_json (structured JSON/JSONL querying) or grep (free text) instead of
reading the whole thing back.
"""

# Marker key on a ToolMessage's `additional_kwargs`.
OFFLOAD_KEY = "offload"

# Above this many messages a Gmail fetch is offloaded however small it is, so a
# large metadata-only scan stays out of the context window.
OFFLOAD_MIN_MESSAGES = 50

# Mining tools surfaced when an offload occurs, chosen by the offload's `fmt`.
# query_json for structured records, grep for free text.
QUERY_JSON_TOOL_NAME = "query_json"
GREP_TOOL_NAME = "grep"
OFFLOAD_JSON_FORMATS = frozenset({"json", "jsonl"})

# In-process bounds for `query_json`: cap how much of an offloaded file we read,
# how many records we parse, and how many queries run at once — so a huge file
# (or many concurrent queries) can't exhaust the API process memory.
MAX_QUERY_INPUT_BYTES = 16 * 1024 * 1024
MAX_QUERY_RECORDS = 20_000
MAX_QUERY_CONCURRENCY = 4

# Host-side execution bounds for the `grep` subprocess (runs in the API process,
# not the sandbox): bound output, wall-clock time, and child memory.
FILTER_TIMEOUT_SECONDS = 20
MAX_FILTER_OUTPUT_CHARS = 30_000
FILTER_MAX_MEMORY_BYTES = 512 * 1024 * 1024
