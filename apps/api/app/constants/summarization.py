# Summarization kicks in earlier (0.60) so large multi-step runs never
# balloon to tens-of-thousands of tokens. Keeps steady-state context narrower.
SUMMARIZATION_TRIGGER_FRACTION = 0.60
SUMMARIZATION_KEEP_TOKENS = 8000  # Keep ~8K tokens after summarization

# Aggressive compaction sheds stale tool observations earlier so per-step
# input tokens stay low and implicit prompt caching keeps hitting on long
# multi-step runs.
COMPACTION_THRESHOLD = 0.40
# Single tool output > ~30k tokens → compact to a workspace file immediately.
# (~4 chars/token, the same estimate this middleware uses for context usage.)
MAX_OUTPUT_CHARS = 120000

# Floor for the context-pressure trigger: over the compaction threshold, outputs
# above this size compact even under MAX_OUTPUT_CHARS; below it, tiny outputs stay inline.
MIN_COMPACTION_SIZE = 500

# LLM-summary tier: compacted ToolMessage carries a model-written digest instead
# of only a file pointer. Input is sampled head+tail; single-attempt with a
# timeout so a slow endpoint can't stall the tool loop (else falls back below).
COMPACTION_SUMMARY_INPUT_HEAD_CHARS = 24_000  # ~6k tokens of prompt
COMPACTION_SUMMARY_INPUT_TAIL_CHARS = 8_000  # ~2k tokens of prompt
COMPACTION_SUMMARY_MAX_CHARS = 4_000  # ~1k tokens in context, vs 30k before
COMPACTION_SUMMARY_TIMEOUT_SECONDS = 30

# Fallback tier: when the workspace is unavailable, truncate in place instead
# of spilling. Head and tail are both kept — dropping either loses schema/first
# records or the totals/errors at the end. ~4 chars/token, ~1k tokens kept.
COMPACTION_FALLBACK_HEAD_CHARS = 3000
COMPACTION_FALLBACK_TAIL_CHARS = 1000
