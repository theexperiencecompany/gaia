"""Constants for the GAIA memory engine."""

from enum import StrEnum

# Local ONNX models (fastembed). Memory must work offline and fast —
# do NOT swap these for cloud models.
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
RERANKER_MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"

# ChromaDB collections holding memory and episode vectors.
CHROMA_MEMORIES_COLLECTION = "gaia_memories"
CHROMA_MEMORY_EPISODES_COLLECTION = "gaia_memory_episodes"

# Ingestion reconciliation (cosine similarity against existing latest facts):
# >= DUPLICATE means the fact already exists verbatim — skip it;
# >= RECONCILE means it may update/extend an existing fact — ask the LLM.
DUPLICATE_SIMILARITY_THRESHOLD = 0.92
RECONCILE_SIMILARITY_THRESHOLD = 0.75

# Hybrid recall pipeline: candidate counts per retriever and the RRF
# fusion constant (k=60 is the canonical value from the RRF paper).
RRF_K = 60
ANN_CANDIDATES = 30
FTS_CANDIDATES = 30
RERANK_CANDIDATES = 30

# Recency boost applied after reranking:
# score *= 1 + RECENCY_BOOST_WEIGHT * e^(-age_days / RECENCY_BOOST_DECAY_DAYS)
RECENCY_BOOST_WEIGHT = 0.15
RECENCY_BOOST_DECAY_DAYS = 30

# Cache TTLs (seconds). Core context is invalidated on every ingestion, so
# the 1h TTL is a backstop; recall is cached briefly per (user, query).
CORE_CONTEXT_CACHE_TTL = 3600
MEMORY_SEARCH_CACHE_TTL = 60

# Category folders form a real directory tree; keep it shallow ("work/gaia").
CATEGORY_PATH_MAX_DEPTH = 2

# Maximum transcript size fed to the extraction LLM (characters). When a
# transcript exceeds the cap we keep the head (opening context) and the tail
# (most recent exchanges) and drop the middle.
EXTRACTION_TRANSCRIPT_MAX_CHARS = 12_000
EXTRACTION_TRANSCRIPT_HEAD_CHARS = 2_000
EXTRACTION_TRANSCRIPT_TAIL_CHARS = 10_000

# Default importance assigned to a fact when the extractor omits it.
DEFAULT_MEMORY_IMPORTANCE = 0.5


class MemoryKind(StrEnum):
    """What a memory row represents."""

    FACT = "fact"
    EXPERIENCE = "experience"


class MemoryRelationType(StrEnum):
    """How a memory version relates to its parent in the supersession chain."""

    UPDATES = "updates"
    EXTENDS = "extends"
    DERIVES = "derives"


class MemoryEntityType(StrEnum):
    """What kind of thing a named entity is."""

    PERSON = "person"
    PLACE = "place"
    ORGANIZATION = "organization"
    PROJECT = "project"
    TOPIC = "topic"
    OTHER = "other"


class ReconcileOutcome(StrEnum):
    """LLM verdict on how a newly extracted fact relates to an existing memory."""

    NEW = "NEW"
    UPDATES = "UPDATES"
    EXTENDS = "EXTENDS"
    DUPLICATE = "DUPLICATE"


class MemoryDocType(StrEnum):
    """Core markdown documents maintained per user."""

    USER_MD = "user_md"
    MEMORY_MD = "memory_md"
    AGENDA_MD = "agenda_md"
    PEOPLE_MD = "people_md"
    INSIGHTS_MD = "insights_md"


class MemorySourceType(StrEnum):
    """Where a memory was ingested from."""

    CONVERSATION = "conversation"
    TOOL = "tool"
    EMAIL = "email"
    MANUAL = "manual"
    MIGRATION = "migration"
