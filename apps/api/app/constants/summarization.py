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

# Floor for the context-pressure trigger: when context usage is over the
# compaction threshold, outputs above this size are compacted even though
# they are under MAX_OUTPUT_CHARS. Below it, offloading costs more than it
# saves, so tiny outputs always stay inline.
MIN_COMPACTION_SIZE = 500

# Fallback tier: when the workspace is unavailable there is nowhere to spill to,
# so the output is truncated in place instead. Head and tail are both kept —
# tool outputs put the schema/first records at the front and totals/errors at
# the end, and dropping either loses the part the model actually reads.
# ~4 chars/token, so this keeps roughly 1k tokens per compacted output.
COMPACTION_FALLBACK_HEAD_CHARS = 3000
COMPACTION_FALLBACK_TAIL_CHARS = 1000
