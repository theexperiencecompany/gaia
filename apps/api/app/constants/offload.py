"""Constants for the workspace-offload + file-mining flow.

When a tool's output is offloaded to a workspace file (by the compaction
middleware, or by a tool that self-offloads), the message carries a structured
marker and the agent mines the file with the `jq`/`grep` tools instead of
reading the whole thing back into context.
"""

# Marker keys: OFFLOAD_KEY on a ToolMessage's `additional_kwargs`; OFFLOAD_RESULT_KEY
# on a self-offloading tool's dict result (lifted into the marker by the tool node).
OFFLOAD_KEY = "offload"
OFFLOAD_RESULT_KEY = "__offload__"

# Mining tools surfaced when an offload occurs, chosen by the offload's `fmt`.
JQ_TOOL_NAME = "jq"
GREP_TOOL_NAME = "grep"
OFFLOAD_JSON_FORMATS = frozenset({"json", "jsonl"})

# Host-side execution bounds for jq/grep. They run in the API process (not the
# sandbox), so bound output, wall-clock time, and child memory to protect the
# process — a jq program can build a huge structure in-memory and emit nothing
# until done, so the output cap alone wouldn't catch it.
FILTER_TIMEOUT_SECONDS = 20
MAX_FILTER_OUTPUT_CHARS = 30_000
# Address-space ceiling for the child (jq/grep). 512 MiB is far above any real
# mining workload but well below the multi-GB a malicious `[range(2e7)]` needs.
FILTER_MAX_MEMORY_BYTES = 512 * 1024 * 1024
