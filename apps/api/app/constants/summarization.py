# Default model for summarization - Gemini Flash 2 for speed and cost
SUMMARIZATION_MODEL = "gemini-2.0-flash"

# Summarization thresholds
SUMMARIZATION_TRIGGER_FRACTION = 0.85  # Trigger at 85% of context window
SUMMARIZATION_KEEP_TOKENS = 8000  # Keep ~8K tokens after summarization

# Compaction thresholds
COMPACTION_THRESHOLD = (
    0.65  # Thread context usage ratio to start compacting all outputs
)
MAX_OUTPUT_CHARS = 20000  # Single tool output > 20k chars → compact immediately to VFS

# Minimum size (chars) to consider for compaction
MIN_COMPACTION_SIZE = 500

# VFS read pagination
MAX_VFS_READ_CHARS = 80000  # ~20K tokens per read chunk

# Stale output masking — size-based decay
STALE_MIN_SIZE = 1000  # Outputs below this are never masked
STALE_SIZE_TIERS: list[tuple[int, int]] = [
    # (max_chars_exclusive, turns_before_mask)
    (5_000, 4),  # 1K-5K chars: mask after 4 turns
    (20_000, 3),  # 5K-20K chars: mask after 3 turns
    (50_000, 2),  # 20K-50K chars: mask after 2 turns (minimum)
]
STALE_DEFAULT_TURNS = 1  # > 50K chars: mask after 1 turn

# Grep output truncation
MAX_GREP_OUTPUT_CHARS = 40000  # ~10K tokens for grep results
