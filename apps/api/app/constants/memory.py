"""Constants for the GAIA memory engine."""

from datetime import UTC, datetime
from enum import StrEnum
import os

from app.constants.chroma import CHROMA_COLLECTION_SUFFIX

# Local ONNX models (fastembed) — must stay offline, do NOT swap for cloud models.
# mxbai-embed-large (1024-dim, ~0.7GB) ranks gold facts top-3 on 6/6 hard implicit
# probes vs 3/6 for bge-small; changing it requires re-embedding via scripts/reembed_memories.py.
EMBEDDING_MODEL_NAME = os.getenv("GAIA_EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1")
EMBEDDING_DIM = int(os.getenv("GAIA_EMBEDDING_DIM", "1024"))
# Appended to Chroma collection names so different embedding dims — and
# concurrent CI lanes sharing one Chroma — never collide (empty = prod default).
_COLLECTION_SUFFIX = CHROMA_COLLECTION_SUFFIX
# jina-reranker-v1-turbo-en (~150MB) measurably beats ms-marco-MiniLM on
# implicit conversational queries: top-3 gold rank 4/6 vs 2/6 at the same ~30ms.
RERANKER_MODEL_NAME = "jinaai/jina-reranker-v1-turbo-en"

# ONNX CPU mem arena retains buffers to fill RAM (~5GB for ~2GB of weights); off
# keeps RSS near model size. Thread cap bounds per-thread arenas. Vectors unchanged.
ONNX_ENABLE_CPU_MEM_ARENA = os.getenv("MEMORY_ONNX_CPU_MEM_ARENA", "0") == "1"
try:
    ONNX_INTRA_OP_THREADS = max(1, int(os.getenv("MEMORY_ONNX_THREADS", "4")))
except ValueError:
    ONNX_INTRA_OP_THREADS = 4

# Optional embedding/reranking sidecar. When this env var holds the sidecar's
# base URL, embed/rerank become HTTP calls so the ~1.8GB of model weights load
# ONCE for the deployment instead of in every process. Unset = load locally.
EMBEDDING_SIDECAR_URL_ENV = "MEMORY_EMBEDDING_SIDECAR_URL"
EMBEDDING_SIDECAR_TIMEOUT_SECONDS = 30.0
# Recall on the user's turn fails fast into retrieval-order ranking rather than
# holding the turn for the 30s client timeout plus retry backoff; ingestion keeps
# the long budget above because a dropped memory save is worse than a slow one.
EMBEDDING_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS = max(
    0.1, float(os.getenv("MEMORY_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS", "5"))
)

# Max in-flight sidecar inferences: more than (cores / ONNX_INTRA_OP_THREADS)
# concurrent calls oversubscribes the CPU past the client timeout above.
# Defaults to that ratio (>= 1); env-overridable per host's core/thread budget.
_default_sidecar_concurrency = max(
    1, (os.cpu_count() or ONNX_INTRA_OP_THREADS) // ONNX_INTRA_OP_THREADS
)
try:
    EMBEDDING_SIDECAR_MAX_CONCURRENCY = max(
        1, int(os.getenv("MEMORY_EMBEDDING_SIDECAR_CONCURRENCY", str(_default_sidecar_concurrency)))
    )
except ValueError:
    EMBEDDING_SIDECAR_MAX_CONCURRENCY = _default_sidecar_concurrency

# Request bounds (#918): a 32-text request of ~1600-char passages measured
# pushing RSS past the prod container limit. Texts beyond MAX_TEXT_CHARS are
# rejected outright (past the model's 512-token window).
EMBEDDING_SIDECAR_MAX_BATCH_TEXTS = int(os.getenv("MEMORY_SIDECAR_MAX_BATCH_TEXTS", "16"))
EMBEDDING_SIDECAR_MAX_BATCH_CHARS = int(os.getenv("MEMORY_SIDECAR_MAX_BATCH_CHARS", "64_000"))
EMBEDDING_SIDECAR_MAX_TEXT_CHARS = int(os.getenv("MEMORY_SIDECAR_MAX_TEXT_CHARS", "65_000"))

# Retries for a transiently-failing sidecar call (503/429/connection reset)
# before giving up, so a brief overload window doesn't drop the save. Clamped
# at the floor — a negative budget would otherwise retry forever.
EMBEDDING_SIDECAR_RETRIES = max(0, int(os.getenv("MEMORY_SIDECAR_RETRIES", "2")))
# Fixed backoff between retry attempts.
EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS = max(
    0.0, float(os.getenv("MEMORY_SIDECAR_RETRY_MAX_WAIT_SECONDS", "5"))
)

# A 503 (overloaded) or 429 (rate-limited) is transient — the sidecar already
# waited out its own slot budget — so it is worth another attempt; any other
# status is the caller's answer.
EMBEDDING_SIDECAR_RETRYABLE_STATUS_CODES = frozenset({429, 503})

# How long a sidecar request may wait for a free inference slot before failing
# with 503 instead of queueing invisibly until the client's own timeout.
EMBEDDING_SIDECAR_SLOT_WAIT_SECONDS = max(
    0.0, float(os.getenv("MEMORY_SIDECAR_SLOT_WAIT_SECONDS", "20"))
)

# Persistent on-disk cache for fastembed model weights. Set in prod to a
# mounted volume so the ~1.85GB download happens ONCE, not every redeploy
# (measured ~148s cold-load). Unset falls back to fastembed's ephemeral default.
MODEL_CACHE_DIR = os.getenv("MEMORY_MODEL_CACHE_DIR") or None

# ChromaDB collections holding memory, episode, and conversation vectors.
CHROMA_MEMORIES_COLLECTION = "gaia_memories" + _COLLECTION_SUFFIX
CHROMA_MEMORY_EPISODES_COLLECTION = "gaia_memory_episodes" + _COLLECTION_SUFFIX
CHROMA_CONVERSATION_CHUNKS_COLLECTION = "gaia_conversation_chunks" + _COLLECTION_SUFFIX

# Raw-conversation retention: extracted facts lose verbatim micro-details, so
# each transcript is also chunked and embedded to keep them searchable verbatim.
TRANSCRIPT_CHUNK_TURNS = 4
TRANSCRIPT_CHUNK_MAX_CHARS = 1_600
# Overlap when a single long turn is split across windows, so an item near a
# window boundary isn't cut in half and stays matchable from either side.
TRANSCRIPT_CHUNK_OVERLAP_CHARS = 200
TRANSCRIPT_CHUNKS_PER_SESSION_CAP = 40
TRANSCRIPT_RECALL_LIMIT = 3

# Reconciliation (cosine similarity): >= RECONCILE sends a fact to the LLM as a
# possible update/extend/duplicate; byte-identical text at >= DUPLICATE collapses
# without an LLM call. Calibrated: paraphrase dupes ~0.96, contradictions 0.75-0.89.
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

# Confidence tiering: CONFIDENT means any absolute signal vouches (dense
# similarity, cross-encoder logit, or FTS anchor); weak results are capped.
# Calibrated to mxbai-embed-large: real matches ~0.50-0.55, unrelated below 0.51.
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

# Optional 1-hop graph expansion: entities on the top results pull in
# sibling memories, which are then reranked alongside the base pool.
GRAPH_EXPANSION_SOURCE_RESULTS = 3
GRAPH_EXPANSION_MAX_SIBLINGS = 3

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

# Optimistic per-user counter mirroring count_live_memories, so the free-cap
# check avoids a Postgres COUNT on the hot path. 24h TTL so any drift self-heals
# on expiry; maintained by INCR/DECR at every mutation site (app/memory/cap_counter.py).
MEMORY_LIVE_COUNT_CACHE_KEY = "user:{user_id}:memory:live_count"
MEMORY_LIVE_COUNT_CACHE_TTL = 86_400

# How long a `state` fact stays live before the nightly sweep forgets it. State
# has no natural expiry the extractor could name ("18 workflows active"), so
# ingestion stamps a flat window; two months balances re-assertion vs. staleness.
STATE_FACT_TTL_DAYS = 60

# Agenda items are facts with ``shelf_life=task``: a commitment with a date is
# useless long after it, but an undated intention deserves a longer leash than
# a state value before the sweep drops it.
AGENDA_ITEM_TTL_DAYS = 90
# Category folder every agenda item files under (it is also a real folder in
# the taxonomy the extraction prompt offers).
AGENDA_CATEGORY_PATH = "agenda"
# How many agenda items the always-injected block renders (the rest stay
# searchable). Sized so a real backlog arrives whole rather than cut to a
# handful — a commitment the agent cannot see is one it silently drops.
AGENDA_INJECTED_ITEM_CAP = 30

# Reconciliation looks at this many nearest existing memories per new fact —
# with 5, older duplicates fell outside the window and stayed live forever,
# since reconciliation could only ever supersede the newest.
RECONCILE_CANDIDATES = 15

# How many recent facts are shown to the extractor as "do NOT re-extract".
RECENT_FACTS_LIMIT = 10

# Near-duplicate gate for journal entries (difflib ratio): one production day
# carried the same discussion five times, reworded. Calibrated: rewordings
# score 0.91-0.95, distinct events 0.40 and below, so 0.85 drops spam with margin.
EPISODE_ENTRY_DEDUPE_RATIO = 0.85

# Per-thread high-water mark for passive ingestion (last extracted message id).
# Without it the whole thread was re-sent every turn — one production
# conversation with 152 checkpoints re-extracted the transcript ~76 times.
MEMORY_INGEST_MARK_KEY = "user:{user_id}:memory:ingested:{thread_id}"
# The mark only has to outlive the gap between two turns of one conversation.
# Losing it degrades to a full re-ingest (the old behaviour), never to a lost
# disclosure, so a generous month is the right side to err on.
MEMORY_INGEST_MARK_TTL = 30 * 86_400
# How many already-ingested messages ride along ahead of the delta so a new
# message that only makes sense in context ("yes, that one") still resolves.
MEMORY_DELTA_CONTEXT_MESSAGES = 6

# Worth-learning gate for conversational ingestion. No message-count or
# tool-call gating (a single disclosure must be remembered): any user message
# with at least this many characters is ingested; trivial turns cost nothing.
MIN_USER_CONTENT_CHARS = 8

# Max LIVE memory facts a free user may accumulate; pro is uncapped. At the
# cap, NEW inserts are skipped (silently, or with an upsell card for add_memory);
# UPDATES still apply. Pricing-card copy derives from this in scripts/payment_setup.py.
FREE_MEMORY_FACT_LIMIT = 50  # TUNE

# Headroom below FREE_MEMORY_FACT_LIMIT within which the cached live count is
# NOT trusted: the free-cap check takes an authoritative COUNT instead, so a
# batch near the cap can never overshoot the hard maximum on stale/drifted cache.
FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN = 10

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
# Safety valve, not a window: user.md/people.md re-derive from EVERY live fact,
# since a freshest-50 rewrite could never be contradicted by the fact it
# corrupted ("Khyati Sheth, Oct 19 2022" became "Khyal Shetal, Oct 19 2026").
CONSOLIDATION_FACTS_LIMIT = 500
# Hard cap on a core document, enforced after rewrite (one retry, then the
# previous version stands) — prompt-only enforcement let agenda.md reach 4,886.
# Matches CORE_CONTEXT_SECTION_MAX_CHARS to avoid trimming or clipping documents.
DOCUMENT_TARGET_MAX_CHARS = 4000

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

# Category folders form a real directory tree; deep enough to segregate
# ("preferences/restaurants"), shallow enough to browse. Paths deeper than
# this are truncated at ingestion.
CATEGORY_PATH_MAX_DEPTH = 3

# Max transcript size fed to the extraction LLM; over the cap, keep head+tail
# and drop the middle. Sized so a ~100k-char session survives whole: a smaller
# cap made the window SLIDE every turn, breaking the byte-prefix cache (measured ~30% hit rate).
EXTRACTION_TRANSCRIPT_MAX_CHARS = 100_000
EXTRACTION_TRANSCRIPT_HEAD_CHARS = 40_000
EXTRACTION_TRANSCRIPT_TAIL_CHARS = 60_000

# Default importance assigned to a fact when the extractor omits it.
DEFAULT_MEMORY_IMPORTANCE = 0.5

# Agent-tool payloads streamed to the frontend (``memory_data`` events) cap
# text so chat payloads stay small; the settings UI fetches full content.
MEMORY_TOOL_CONTENT_MAX_CHARS = 400
MEMORY_TOOL_DOCUMENT_MAX_CHARS = 4000

# GET /memory/episodes: default lookback window and the hard range cap.
MEMORY_EPISODES_DEFAULT_DAYS = 14
MEMORY_EPISODES_MAX_RANGE_DAYS = 90

# Relevance cutoff: keep only candidates whose PRE-boost blended relevance is
# at least this fraction of the pool's best. Blend is 0.6*sigmoid(rerank logit)
# + 0.4*(cosine/best cosine): real matches cluster ~0.85-1.0, tail below 0.4.
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


class MemoryShelfLife(StrEnum):
    """How long an extracted assertion stays true — decides where it is stored.

    TASK and JOURNAL never reach the memories table: the extractor uses
    them to route a commitment to the agenda and an event (or something GAIA
    itself produced) to the journal, instead of freezing either as a fact.
    """

    DURABLE = "durable"
    STATE = "state"
    TASK = "task"
    JOURNAL = "journal"


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


# On-disk filenames for the core documents in the /workspace/memory projection.
MEMORY_DOC_FILENAMES: dict[MemoryDocType, str] = {
    MemoryDocType.USER_MD: "user.md",
    MemoryDocType.MEMORY_MD: "memory.md",
    MemoryDocType.AGENDA_MD: "agenda.md",
    MemoryDocType.PEOPLE_MD: "people.md",
}

# Stands in for what a document lost when it overran its budget. Fixed text, so
# the notice never itself grows with the content it replaces.
CORE_CONTEXT_TRUNC_MARKER = "\n…[document clipped to bound prompt size]…\n"

# Per-section bounds: a single head/tail cut let an oversized agenda eat the
# journal, so each section has its own budget. A runaway backstop, NOT a diet —
# bounds sit above a healthy document (measured: agenda.md reached 4,886).
CORE_CONTEXT_SECTION_MAX_CHARS: dict[MemoryDocType, int] = {
    MemoryDocType.USER_MD: 4_000,
    MemoryDocType.MEMORY_MD: 4_000,
    MemoryDocType.AGENDA_MD: 3_000,
}


class MemorySourceType(StrEnum):
    """Where a memory was ingested from."""

    CONVERSATION = "conversation"
    TOOL = "tool"
    EMAIL = "email"
    MANUAL = "manual"
    MIGRATION = "migration"


# --- One-time memory backfill (daily cron `backfill_active_users`) ----------
# Users created before the memory pipeline shipped never went through
# memory_node; a daily cron seeds them once. SET TO THE PRODUCTION DEPLOY DATE.
MEMORY_BACKFILL_ELIGIBLE_BEFORE = datetime(2026, 6, 15, tzinfo=UTC)
# Only backfill users seen within this window — skip long-dormant accounts.
MEMORY_BACKFILL_ACTIVE_DAYS = 30
# Per-run cap so the backlog drains over several days instead of spiking the
# extraction LLM (the marker makes each run resume where the last left off).
MEMORY_BACKFILL_MAX_USERS_PER_RUN = 50
# Most-recent conversations replayed per user.
MEMORY_BACKFILL_MAX_CONVERSATIONS = 100
