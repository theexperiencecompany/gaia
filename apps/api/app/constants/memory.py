"""Constants for the GAIA memory engine."""

from datetime import UTC, datetime
from enum import StrEnum
import os

from app.constants.chroma import CHROMA_COLLECTION_SUFFIX

# Local ONNX models (fastembed). Memory must work offline and fast —
# do NOT swap these for cloud models.
# mxbai-embed-large (1024-dim, ~0.7GB, ~14ms/query CPU) ranks the gold fact
# top-3 on 6/6 hard implicit probes vs 3/6 for bge-small — it is what closes
# the "vet appointment -> dog fact" class of semantic hops. Changing the model
# requires re-embedding stored vectors: scripts/reembed_memories.py.
# Env-overridable so a smaller model (e.g. BAAI/bge-base-en-v1.5, 768-dim,
# ~0.5GB) can be swapped in for memory-constrained hosts or A/B comparison.
EMBEDDING_MODEL_NAME = os.getenv("GAIA_EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1")
EMBEDDING_DIM = int(os.getenv("GAIA_EMBEDDING_DIM", "1024"))
# Appended to the Chroma collection names so runs with different embedding
# dimensions — and concurrent CI lanes sharing one Chroma — never collide in
# the same collection (empty = prod default). Defined once in constants/chroma.py
# so every GAIA collection, not just the memory ones, carries the same namespace.
_COLLECTION_SUFFIX = CHROMA_COLLECTION_SUFFIX
# jina-reranker-v1-turbo-en (~150MB) measurably beats ms-marco-MiniLM on
# implicit conversational queries ("what do I do for a living" -> the job
# fact): top-3 gold rank 4/6 vs 2/6 on our probe set at the same ~30ms.
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

# Max in-flight inferences the sidecar runs at once. Each inference uses
# ONNX_INTRA_OP_THREADS cores, so more than (cores / threads) concurrent calls
# oversubscribe the CPU and inflate every caller's latency past the client
# timeout above. Default to that ratio (>= 1); env-overridable for hosts with a
# different core/thread budget.
_default_sidecar_concurrency = max(
    1, (os.cpu_count() or ONNX_INTRA_OP_THREADS) // ONNX_INTRA_OP_THREADS
)
try:
    EMBEDDING_SIDECAR_MAX_CONCURRENCY = max(
        1, int(os.getenv("MEMORY_EMBEDDING_SIDECAR_CONCURRENCY", str(_default_sidecar_concurrency)))
    )
except ValueError:
    EMBEDDING_SIDECAR_MAX_CONCURRENCY = _default_sidecar_concurrency

# Request bounds (#918). ONNX activation memory scales with batch x tokens:
# fastembed's default internal batch of 256 texts materializes multi-GB peaks
# (measured: one 32-text request of ~1600-char passages pushed peak RSS past
# the prod container limit), so every fastembed forward pass is capped to
# MAX_BATCH_TEXTS and oversized HTTP calls are split into chunks of at most
# MAX_BATCH_TEXTS / MAX_BATCH_CHARS before leaving the client. Single texts
# beyond MAX_TEXT_CHARS are rejected outright - they tokenize far beyond the
# model's 512-token window and are always a caller bug. Vectors are unchanged
# by either split (mean pooling is per sequence; measured cosine delta < 1e-7).
EMBEDDING_SIDECAR_MAX_BATCH_TEXTS = int(os.getenv("MEMORY_SIDECAR_MAX_BATCH_TEXTS", "16"))
EMBEDDING_SIDECAR_MAX_BATCH_CHARS = int(os.getenv("MEMORY_SIDECAR_MAX_BATCH_CHARS", "64_000"))
EMBEDDING_SIDECAR_MAX_TEXT_CHARS = int(os.getenv("MEMORY_SIDECAR_MAX_TEXT_CHARS", "65_000"))

# How many times a transiently-failing sidecar call (503/429/connection reset)
# is retried before giving up — memory saves must survive a brief overload
# window instead of being dropped, while persistent failures still fail loud.
# Clamped at the floor: a negative budget would retry forever, which no
# misconfiguration should be able to cause.
EMBEDDING_SIDECAR_RETRIES = max(0, int(os.getenv("MEMORY_SIDECAR_RETRIES", "2")))
# Fixed backoff between retry attempts.
EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS = max(
    0.0, float(os.getenv("MEMORY_SIDECAR_RETRY_MAX_WAIT_SECONDS", "5"))
)

# How long a sidecar request may wait for a free inference slot before failing
# with 503 instead of queueing invisibly until the client's own timeout.
EMBEDDING_SIDECAR_SLOT_WAIT_SECONDS = max(
    0.0, float(os.getenv("MEMORY_SIDECAR_SLOT_WAIT_SECONDS", "20"))
)

# Persistent on-disk cache for the fastembed model weights. Set in prod (on the
# embedding sidecar) to a mounted volume so the ~1.85GB download happens ONCE
# rather than on every restart/redeploy (measured ~148s cold-load). Unset falls
# back to fastembed's ephemeral default, which is fine for local dev.
MODEL_CACHE_DIR = os.getenv("MEMORY_MODEL_CACHE_DIR") or None

# ChromaDB collections holding memory, episode, and conversation vectors.
CHROMA_MEMORIES_COLLECTION = "gaia_memories" + _COLLECTION_SUFFIX
CHROMA_MEMORY_EPISODES_COLLECTION = "gaia_memory_episodes" + _COLLECTION_SUFFIX
CHROMA_CONVERSATION_CHUNKS_COLLECTION = "gaia_conversation_chunks" + _COLLECTION_SUFFIX

# Raw-conversation retention: extracted facts compress a conversation, which
# loses verbatim micro-details ("the 27th item in that list you gave me").
# Each ingested transcript is also chunked and embedded so those details stay
# searchable verbatim — the tier full-context systems win with.
TRANSCRIPT_CHUNK_TURNS = 4
TRANSCRIPT_CHUNK_MAX_CHARS = 1_600
# Overlap when a single long turn is split across windows, so an item near a
# window boundary isn't cut in half and stays matchable from either side.
TRANSCRIPT_CHUNK_OVERLAP_CHARS = 200
TRANSCRIPT_CHUNKS_PER_SESSION_CAP = 40
TRANSCRIPT_RECALL_LIMIT = 3

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

# How long a ``state`` fact stays live before the nightly sweep forgets it.
# State is a value that was only true as of a moment ("18 workflows active",
# "Gmail is disconnected"); it has no natural expiry date the extractor could
# name, so ingestion stamps a flat window and the sweep retires it. Two months
# is long enough that a still-true value gets re-asserted by normal use and
# short enough that a stale one stops being injected into every prompt.
STATE_FACT_TTL_DAYS = 60

# Agenda items are facts with ``shelf_life=task``: a commitment with a date is
# useless long after it, but an undated intention deserves a longer leash than
# a state value before the sweep drops it.
AGENDA_ITEM_TTL_DAYS = 90
# Category folder every agenda item files under (it is also a real folder in
# the taxonomy the extraction prompt offers).
AGENDA_CATEGORY_PATH = "agenda"
# How many agenda items the always-injected block renders. The rest stay
# searchable; the injected block is a reminder, not the whole backlog. Sized
# so a real backlog arrives whole (30 items of typical length sit inside the
# agenda's injection bound below) rather than being cut to a handful: a
# commitment the agent cannot see is one it silently drops.
AGENDA_INJECTED_ITEM_CAP = 30

# Reconciliation looks at this many nearest existing memories per new fact.
# Sized so a subject-attribute already stated several ways (the same partner's
# anniversary written five times) still has every live variant in the candidate
# set — with 5 the older duplicates fell outside the window and reconciliation
# could only ever supersede the newest of them, so the rest stayed live forever.
RECONCILE_CANDIDATES = 15

# How many recent facts are shown to the extractor as "do NOT re-extract".
RECENT_FACTS_LIMIT = 10

# Near-duplicate gate for journal entries (difflib ratio on normalized text).
# The extractor's "do NOT repeat" instruction cannot stop a paraphrase, and
# back-to-back retains race past the journal read — one production day carried
# the same discussion five times, reworded. Calibrated on those real pairs:
# true rewordings score 0.91-0.95, genuinely distinct same-day events 0.40 and
# below, so 0.85 drops the spam with a wide margin over real events.
EPISODE_ENTRY_DEDUPE_RATIO = 0.85

# Per-thread high-water mark for passive ingestion: the id of the last message
# already extracted from. Without it the whole thread was re-sent to the
# extractor every turn — one production conversation with 152 checkpoints
# re-extracted the same transcript roughly 76 times.
MEMORY_INGEST_MARK_KEY = "user:{user_id}:memory:ingested:{thread_id}"
# The mark only has to outlive the gap between two turns of one conversation.
# Losing it degrades to a full re-ingest (the old behaviour), never to a lost
# disclosure, so a generous month is the right side to err on.
MEMORY_INGEST_MARK_TTL = 30 * 86_400
# How many already-ingested messages ride along ahead of the delta so a new
# message that only makes sense in context ("yes, that one") still resolves.
MEMORY_DELTA_CONTEXT_MESSAGES = 6

# Worth-learning gate for conversational ingestion (memory_node). There is NO
# message-count or tool-call gating: a single disclosure ("my name is Sam")
# must be remembered. A turn is ingested whenever any user message carries at
# least this many characters of real text — the extraction LLM then decides if
# anything durable is present, so trivial turns ("hi", "thanks") cost nothing.
MIN_USER_CONTENT_CHARS = 8

# Max number of LIVE memory facts (is_latest, not forgotten) a free user may
# accumulate. At the cap, NEW fact inserts are skipped (passive ingestion
# silently, the explicit add_memory tool with an upsell card); UPDATES to
# existing facts still apply and reads are never gated. Pro is uncapped.
# The free pricing-card copy ("N saved memories") is derived from this constant
# in scripts/payment_setup.py, so it stays in sync automatically when it changes.
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
# Upper bound on how many live facts feed one core-document rewrite. This is a
# safety valve, not a window: user.md and people.md are re-derived from EVERY
# live durable fact in their categories, because a rewrite fed only the freshest
# 50 could never be contradicted by the fact it corrupted — that is how "Khyati
# Sheth, October 19 2022" became "Khyal Shetal, anniversary Oct 19 2026" in the
# always-injected document while five live memories still said otherwise.
CONSOLIDATION_FACTS_LIMIT = 500
# Hard cap on a core document. Enforced in code after the rewrite (one retry
# with an explicit trim instruction, then the previous version stands) — the
# prompt asking nicely was the only enforcement, and agenda.md reached 4,886.
# Matches the per-document injection bound in CORE_CONTEXT_SECTION_MAX_CHARS:
# a write cap below the read bound would trim knowledge the prompt had room
# for, and one above it would write documents that arrive clipped every turn.
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

# Maximum transcript size fed to the extraction LLM (characters). When a
# transcript exceeds the cap we keep the head (opening context) and the tail
# (most recent exchanges) and drop the middle. Sized so a long multi-day
# session (~100k chars) survives whole — truncation loses mid-conversation
# details that the user may ask about weeks later, and the sliding window
# also breaks the lane's byte-prefix cache (below).
#
# Cache note: the extraction call runs 1-2x per turn; the transcript is the
# byte-prefix cache's payload. With a small cap the head+tail window SLIDES
# every turn, so the byte prefix breaks at the truncation marker and the whole
# transcript re-sends uncached (measured ~30% hit on the lane). The cap is
# therefore sized so real conversations stay under it and the transcript is
# append-only — the prefix then extends through it and only the newest
# exchange is uncached. (The original 10k cap bounded the extraction's cache
# footprint when it shared the conversation's provider cache; it has run on
# direct Gemini since — a separate cache store — so that constraint is gone.)
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

# Relevance cutoff applied to every recall: drop the long tail of weak matches
# by keeping only candidates whose PRE-boost blended relevance is at least this
# fraction of the pool's best pre-boost relevance (boosts reorder results but
# never decide survival). The blended base is 0.6 * sigmoid(rerank logit)
# + 0.4 * (cosine / best cosine) — both terms absolute-preserving, so real
# matches cluster near the top (~0.85-1.0 of the best) while faintly-related
# tail facts land well below 0.4 of it, and a hair-thin gap between two real
# answers stays hair-thin instead of being stretched to 1.0-vs-0.0 as the old
# min-max scaling did. This keeps prompt-injected context and the search UI
# free of noise without deleting close runner-up facts.
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

    ``TASK`` and ``JOURNAL`` never reach the memories table: the extractor uses
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

# Per-section bounds on the always-injected core-context block. A single
# head/tail cut over the whole volatile block let an oversized agenda eat the
# journal instead of itself; each section now carries its own budget, so a
# runaway section can only truncate itself.
#
# These are a runaway backstop, NOT a diet. Memory is the product: the bounds
# sit above what a healthy document actually is, so the normal case is injected
# whole and only a document that has genuinely gone wrong is ever clipped.
# Measured against production (user.md 3,077 / memory.md 3,920 / agenda.md
# 4,886), the two profile documents land inside their bound untouched and only
# the agenda — the one that ran away — is bounded, which its item cap
# (AGENDA_INJECTED_ITEM_CAP) now keeps it under anyway.
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
# Users created before the live memory pipeline shipped have conversation
# history that never went through memory_node, so a daily cron seeds it once.
#
# SET THIS TO THE PRODUCTION DEPLOY DATE of the memory system: users created on
# or after it already get memory live during chats, so they're skipped (no
# wasted extraction, no confusing "we organized your memories" notification).
MEMORY_BACKFILL_ELIGIBLE_BEFORE = datetime(2026, 6, 15, tzinfo=UTC)
# Only backfill users seen within this window — skip long-dormant accounts.
MEMORY_BACKFILL_ACTIVE_DAYS = 30
# Per-run cap so the backlog drains over several days instead of spiking the
# extraction LLM (the marker makes each run resume where the last left off).
MEMORY_BACKFILL_MAX_USERS_PER_RUN = 50
# Most-recent conversations replayed per user.
MEMORY_BACKFILL_MAX_CONVERSATIONS = 100
