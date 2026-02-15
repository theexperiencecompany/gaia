# Default model for summarization - Gemini Flash 2 for speed and cost
SUMMARIZATION_MODEL = "gemini-2.0-flash"

# Summarization thresholds
SUMMARIZATION_TRIGGER_FRACTION = 0.85  # Trigger at 85% of context window
SUMMARIZATION_KEEP_TOKENS = 8000  # Keep ~8K tokens after summarization

# Compaction thresholds
COMPACTION_THRESHOLD = (
    0.65  # Thread context usage ratio to start compacting all outputs
)
MAX_OUTPUT_CHARS = 5000  # Single tool output > 5k chars → compact immediately to VFS

# Minimum size (chars) to consider for compaction
MIN_COMPACTION_SIZE = 500
