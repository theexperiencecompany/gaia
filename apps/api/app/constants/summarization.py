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
# Single tool output > ~30k tokens → compact to a workspace file immediately.
# (~4 chars/token, the same estimate this middleware uses for context usage.)
MAX_OUTPUT_CHARS = 120000

# Floor below which a tool output is never compacted (~30k tokens). Modern
# models handle this much context comfortably, so small/medium outputs stay
# inline rather than getting pushed to a file the agent has to re-read.
MIN_COMPACTION_SIZE = 120000
