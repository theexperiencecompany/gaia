"""Constants for the Gmail custom tool module.

Kept in its own file so the tools module reads as a sequence of named
operations, not a wall of magic numbers.
"""

# Gmail REST base + toolkit slug passed to ``proxy_request_sync``.
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
GMAIL_TOOLKIT = "GMAIL"

# Per-page cap Gmail actually accepts for ``users.me.messages``.
GMAIL_MAX_PAGE_SIZE = 500

# Hard cap Gmail enforces on ``users.me.messages.batchModify`` ids per request.
# Larger mutations must be split into chunks or the whole call is rejected.
GMAIL_BATCH_MODIFY_CAP = 1000

# ``users.me.messages.get`` format values: "full" includes the MIME payload
# (needed only when the body will be returned); "metadata" returns headers +
# labels + snippet only.
GMAIL_FORMAT_FULL = "full"
GMAIL_FORMAT_METADATA = "metadata"

# Bounded fan-out for the per-message GET calls within one list page. The
# handler runs sync (off-loop), so a small thread pool turns up to
# MAX_ABSOLUTE_MESSAGES sequential round-trips into a handful of batches.
FETCH_CONCURRENCY = 8

# Absolute ceiling on total messages aggregated by a single tool call.
# Two pages at the Gmail per-page cap is the hard upper bound, anything
# higher can't be reached without more pages and would change semantics.
MAX_ABSOLUTE_MESSAGES = 2 * GMAIL_MAX_PAGE_SIZE

# Default message cap per named timeframe. Tuned to Gmail's per-page cap (500)
# and the GAIA compaction threshold (~8KB inline).
NAMED_TIMEFRAME_DEFAULT_MAX: dict[str, int] = {
    "today": 100,
    "yesterday": 100,
    "tomorrow": 100,
    "this_week": 200,
    "last_week": 200,
    "next_week": 200,
}

# Default cap for a relative "last N days" window, by its length: the first
# (max_days, cap) covering the window wins, longer ones take the long cap.
RELATIVE_TIMEFRAME_DEFAULT_MAX: tuple[tuple[int, int], ...] = ((3, 100), (7, 200), (14, 400))
RELATIVE_TIMEFRAME_LONG_MAX = 500

# Cap when the call names no timeframe.
NO_TIMEFRAME_DEFAULT_MAX = 100

# Crossing this many chars (~30k tokens) writes a JSONL file (one message per
# line) and returns a digest + read_plan. GMAIL_FETCH_MESSAGES is excluded from
# the generic compaction middleware, so this is the sole offload trigger.
INLINE_LIMIT_CHARS = 120_000

# Offload file naming + sandbox-visible path.
OFFLOAD_DIR = "gmail"
OFFLOAD_FILE_PREFIX = "inbox_summary_"
OFFLOAD_PREVIEW_SIZE = 10

# Above this many aggregated messages we always offload to a JSONL file and
# return a read-plan, even when the serialized payload fits under
# INLINE_LIMIT_CHARS. Keeps large metadata-only scans out of the context window.
OFFLOAD_MIN_MESSAGES = 50

# Read-plan chunking: an offloaded JSONL (one message per line) is split into
# contiguous line ranges each subagent reads via read(offset, limit). Chunk
# count is the max of the by-message/by-byte estimates, capped at MAX_READ_SUBAGENTS.
CHUNK_TARGET_MESSAGES = 25
CHUNK_TARGET_BYTES = 50_000
MAX_READ_SUBAGENTS = 4

# How many days a "d"/"w"/"m"/"y" relative timeframe spans.
_DAYS_PER_UNIT: dict[str, int] = {"d": 1, "w": 7, "m": 30, "y": 365}
