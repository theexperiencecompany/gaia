# Default model for summarization - Gemini Flash 2 for speed and cost
SUMMARIZATION_MODEL = "gemini-2.0-flash"

# Summarization thresholds
SUMMARIZATION_TRIGGER_FRACTION = 0.85  # Trigger at 85% of context window
SUMMARIZATION_KEEP_TOKENS = 8000  # Keep ~8K tokens after summarization

# Compaction thresholds
COMPACTION_THRESHOLD = 0.65  # Context usage ratio to start compacting
MAX_OUTPUT_TOKENS = 60000  # Max tokens for a single tool output

# Minimum size (chars) to consider for compaction
MIN_COMPACTION_SIZE = 500
