# Default model for summarization — small/fast/cheap provider model.
SUMMARIZATION_MODEL = "gemini-2.0-flash"

# Summarization kicks in earlier (0.60) so large multi-step runs never
# balloon to tens-of-thousands of tokens. Keeps steady-state context narrower.
SUMMARIZATION_TRIGGER_FRACTION = 0.60
SUMMARIZATION_KEEP_TOKENS = 8000  # Keep ~8K tokens after summarization

# Aggressive compaction sheds stale tool observations earlier so per-step
# input tokens stay low and implicit prompt caching keeps hitting on long
# multi-step runs.
COMPACTION_THRESHOLD = 0.40
# Single tool output > 8k chars → compact to VFS immediately.
MAX_OUTPUT_CHARS = 8000

# Minimum size (chars) to consider for compaction
MIN_COMPACTION_SIZE = 500
