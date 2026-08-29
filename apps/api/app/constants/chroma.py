"""
ChromaDB Constants.

Tunables for the ChromaDB-backed LangGraph store.
"""

# Caps concurrent ChromaDB HTTP connections process-wide (shared across every
# _apply_put_ops call, not just within one batch — see loop_bound_semaphore
# usage in chroma_store.py) to avoid EMFILE 24 (per-process fd limit, not
# system-wide ENFILE). gaia-backend's RLIMIT_NOFILE soft limit is 1024 with
# ~72 fds baseline usage, so 20 clears it with wide margin even when startup
# fans out indexing across every provider toolkit concurrently.
MAX_CONCURRENT_CHROMA_WRITES = 20

# How long a namespace's indexed-signature marker survives in Redis. It is a
# fast-path hint only (the ChromaDB hash diff is the source of truth), so a day
# is plenty — a stale or missing marker just costs one extra diff read.
TOOLS_INDEX_CACHE_TTL_SECONDS = 86_400

# Cross-replica seed lock for tool/subagent indexing. On a cold or wiped Chroma,
# every replica and worker would otherwise embed the full tool+subagent catalog
# at once (N× the Gemini embedding cost) on startup. The lease is short and
# watchdog-renewed; a follower that can't acquire within the window falls back to
# running the (idempotent, hash-diffed) seed unsynchronized rather than skipping.
TOOLS_SEED_LOCK_KEY_PREFIX = "lock:chroma:tools-seed:"
TOOLS_SEED_LOCK_LEASE_SECONDS = 30
TOOLS_SEED_LOCK_RENEW_SECONDS = 10
TOOLS_SEED_LOCK_ACQUIRE_TIMEOUT_SECONDS = 120
# Hard cap on renewal: past this the lease expires so a wedged seed can't block
# every replica's indexing forever. Well above the real embedding time (the
# ~1.6k-tool catalog batches in a minute or two).
TOOLS_SEED_LOCK_MAX_HOLD_SECONDS = 300
