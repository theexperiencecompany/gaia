"""Constants for the GAIA memory engine."""

from enum import StrEnum

# Local ONNX models (fastembed). Memory must work offline and fast —
# do NOT swap these for cloud models.
# mxbai-embed-large (1024-dim, ~0.7GB, ~14ms/query CPU) ranks the gold fact
# top-3 on 6/6 hard implicit probes vs 3/6 for bge-small — it is what closes
# the "vet appointment -> dog fact" class of semantic hops. Changing the model
# requires re-embedding stored vectors: scripts/reembed_memories.py.
EMBEDDING_MODEL_NAME = "mixedbread-ai/mxbai-embed-large-v1"
EMBEDDING_DIM = 1024
# jina-reranker-v1-turbo-en (~150MB) measurably beats ms-marco-MiniLM on
# implicit conversational queries ("what do I do for a living" -> the job
# fact): top-3 gold rank 4/6 vs 2/6 on our probe set at the same ~30ms.
RERANKER_MODEL_NAME = "jinaai/jina-reranker-v1-turbo-en"

# ChromaDB collections holding memory and episode vectors.
CHROMA_MEMORIES_COLLECTION = "gaia_memories"
CHROMA_MEMORY_EPISODES_COLLECTION = "gaia_memory_episodes"

# Ingestion reconciliation (cosine similarity against existing latest facts):
# >= RECONCILE means a fact is close enough to an existing one that it might
# update/extend/duplicate it — those go to the LLM. Within that band, a fact
# whose normalized text is byte-identical to a candidate at >= DUPLICATE
# similarity is collapsed without an LLM call. Similarity alone never auto-
# drops a fact: "deadline March 10" vs "deadline March 17" embed near-
# identically but the second is an UPDATE, not a duplicate — only the LLM
# (or exact-text match) may decide.
# Calibrated to mxbai-embed-large doc-doc cosines: paraphrase duplicates
# ~0.96, contradictions/value-changes 0.75-0.89, same-person-different-topic
# ~0.61, unrelated ~0.38.
DUPLICATE_SIMILARITY_THRESHOLD = 0.92
RECONCILE_SIMILARITY_THRESHOLD = 0.70

# Hybrid recall pipeline: candidate counts per retriever and the RRF
# fusion constant (k=60 is the canonical value from the RRF paper).
RRF_K = 60
ANN_CANDIDATES = 30
FTS_CANDIDATES = 30
RERANK_CANDIDATES = 30
DEFAULT_RECALL_LIMIT = 8

# Final ranking blends cross-encoder relevance with fused retrieval rank —
# the two fail on different query shapes, and the blend rescues both.
RERANK_BLEND_WEIGHT = 0.6

# Confidence tiering: a result is CONFIDENT when any absolute signal vouches
# for it — strong dense similarity, a strong cross-encoder logit, or a keyword
# (FTS) anchor. Confident results pass freely; weak ones (plausible but
# unproven) are capped so an unanswerable query returns at most a couple of
# semi-related items instead of a page of noise. Local-model score
# distributions overlap, so a hard empty-on-irrelevant gate would cost recall.
# Calibrated to mxbai-embed-large's cosine scale (hard-but-real matches sit
# at ~0.50-0.55; unrelated content mostly below 0.51).
CONFIDENT_COSINE = 0.515
CONFIDENT_RERANK_LOGIT = -2.5
MAX_WEAK_RESULTS = 4

# Recency boost applied after reranking:
# score *= 1 + RECENCY_BOOST_WEIGHT * e^(-age_days / RECENCY_BOOST_DECAY_DAYS)
RECENCY_BOOST_WEIGHT = 0.15
RECENCY_BOOST_DECAY_DAYS = 30

# Importance boost applied after reranking:
# score *= IMPORTANCE_BOOST_BASE + IMPORTANCE_BOOST_WEIGHT * importance
IMPORTANCE_BOOST_BASE = 0.8
IMPORTANCE_BOOST_WEIGHT = 0.4

# Optional 1-hop graph expansion after reranking: entities on the top
# results pull in sibling memories at a low fixed score.
GRAPH_EXPANSION_SOURCE_RESULTS = 3
GRAPH_EXPANSION_MAX_SIBLINGS = 3
GRAPH_EXPANSION_SCORE = 0.05

# Episode (journal) search: verbatim entry matching looks back this many
# days; query tokens shorter than the minimum are noise and dropped.
EPISODE_SEARCH_DAYS = 14
EPISODE_ENTRY_CANDIDATES = 20
EPISODE_SEARCH_MIN_TOKEN_LENGTH = 3
DEFAULT_EPISODE_RECALL_LIMIT = 5

# Cache TTLs (seconds). Core context is invalidated on every ingestion, so
# the 1h TTL is a backstop; recall is cached briefly per (user, query).
CORE_CONTEXT_CACHE_TTL = 3600
MEMORY_SEARCH_CACHE_TTL = 60

# Redis key templates. Every ingestion invalidates both: search results are
# stale the moment a fact lands, and the core context embeds recent facts.
MEMORY_SEARCH_CACHE_PATTERN = "user:{user_id}:memories:*"
CORE_CONTEXT_CACHE_KEY = "user:{user_id}:memory:core"

# Reconciliation looks at this many nearest existing memories per new fact.
RECONCILE_CANDIDATES = 5

# How many recent facts are shown to the extractor as "do NOT re-extract".
RECENT_FACTS_LIMIT = 10

# Worth-learning gate for conversational ingestion (memory_node). There is NO
# message-count or tool-call gating: a single disclosure ("my name is Aryan")
# must be remembered. A turn is ingested whenever any user message carries at
# least this many characters of real text — the extraction LLM then decides if
# anything durable is present, so trivial turns ("hi", "thanks") cost nothing.
MIN_USER_CONTENT_CHARS = 8

# Max length of an agent/user-supplied forget reason (matches the DB column).
FORGET_REASON_MAX_CHARS = 200

# Core documents keep this many previous versions in their history column.
DOCUMENT_HISTORY_LIMIT = 10

# Consolidation (core-doc rewriting) is debounced per user: every ingestion
# merges its affected doc types into a Redis pending set, and a single
# in-process waiter rewrites the docs once the debounce window elapses.
CONSOLIDATION_DEBOUNCE_SECONDS = 120
CONSOLIDATION_PENDING_KEY = "user:{user_id}:memory:consolidate:pending"
CONSOLIDATION_PENDING_TTL = 3600
# How many of the freshest facts feed each core-document rewrite.
CONSOLIDATION_FACTS_LIMIT = 50
# insights.md looks back this many days of episode summaries.
CONSOLIDATION_EPISODE_DAYS = 30
# Soft cap each consolidation prompt enforces on a core document.
DOCUMENT_TARGET_MAX_CHARS = 2500

# /workspace/memory projection: journal pages older than this are dropped
# from the on-disk view (Postgres keeps the full history).
PROJECTION_JOURNAL_DAYS = 30

# Core-document preview length on the settings-UI overview screen.
DOCUMENT_PREVIEW_CHARS = 280

# Wall-clock format for timestamped episode journal entries.
EPISODE_ENTRY_TIME_FORMAT = "%H:%M"

# Always-injected "recent activity": today is shown as its most recent few raw
# entries (continuity), never the whole day. Past days collapse to their
# one-line rollover summary. The full journal stays available via search.
RECENT_ACTIVITY_ENTRY_CAP = 6

# Category folders form a real directory tree; keep it shallow ("work/gaia").
CATEGORY_PATH_MAX_DEPTH = 2

# Maximum transcript size fed to the extraction LLM (characters). When a
# transcript exceeds the cap we keep the head (opening context) and the tail
# (most recent exchanges) and drop the middle. Sized so a long single session
# (~20k chars) survives whole — truncation loses mid-conversation details
# that the user may ask about weeks later.
EXTRACTION_TRANSCRIPT_MAX_CHARS = 24_000
EXTRACTION_TRANSCRIPT_HEAD_CHARS = 4_000
EXTRACTION_TRANSCRIPT_TAIL_CHARS = 20_000

# Default importance assigned to a fact when the extractor omits it.
DEFAULT_MEMORY_IMPORTANCE = 0.5

# Agent-tool payloads streamed to the frontend (``memory_data`` events) cap
# text so chat payloads stay small; the settings UI fetches full content.
MEMORY_TOOL_CONTENT_MAX_CHARS = 400
MEMORY_TOOL_DOCUMENT_MAX_CHARS = 4000

# GET /memory/episodes: default lookback window and the hard range cap.
MEMORY_EPISODES_DEFAULT_DAYS = 14
MEMORY_EPISODES_MAX_RANGE_DAYS = 90

# Relevance cutoff applied to every recall: drop the long tail of weak matches
# by keeping only results scoring at least this fraction of the top hit. Hybrid
# recall returns a sharp relevance cliff (strong matches ~1.0+, noise <0.1), so
# a relative floor cleanly separates the two without a brittle absolute one.
# This keeps both prompt-injected context and the search UI free of noise.
RELEVANCE_DROPOFF_RATIO = 0.4

# Request-body length caps. A memory is one atomic fact, so it stays short;
# a core document is a living markdown page, so it gets far more room.
MEMORY_CONTENT_MAX_CHARS = 10_000
MEMORY_DOCUMENT_CONTENT_MAX_CHARS = 50_000
CATEGORY_PATH_MAX_CHARS = 120

# Canonical UUID-string pattern for memory-id path parameters.
UUID_PATH_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


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


# On-disk filenames for the core documents in the /workspace/memory projection.
MEMORY_DOC_FILENAMES: dict[MemoryDocType, str] = {
    MemoryDocType.USER_MD: "user.md",
    MemoryDocType.MEMORY_MD: "memory.md",
    MemoryDocType.AGENDA_MD: "agenda.md",
    MemoryDocType.PEOPLE_MD: "people.md",
    MemoryDocType.INSIGHTS_MD: "insights.md",
}


class MemorySourceType(StrEnum):
    """Where a memory was ingested from."""

    CONVERSATION = "conversation"
    TOOL = "tool"
    EMAIL = "email"
    MANUAL = "manual"
    MIGRATION = "migration"
