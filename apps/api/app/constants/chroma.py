"""ChromaDB collection naming, shared by every feature that owns a collection.

One Chroma process can be shared by several concurrent test lanes (see
``scripts/ci/test-services.sh``), and Chroma has no database/namespace
concept — collections are a single flat namespace per server. So the *name* is
the namespace: ``GAIA_CHROMA_COLLECTION_SUFFIX`` is appended to every
collection GAIA creates, which is what keeps lane r0's ``notes_r0`` from
being wiped by lane r1's teardown.

The suffix also predates that use: it separates runs that embed with different
models/dimensions, which cannot share a collection. Empty (the default) is the
production naming, so unset envs reproduce the historical names byte for byte.

Also holds tunables for the ChromaDB-backed LangGraph store.
"""

import os

CHROMA_COLLECTION_SUFFIX = os.getenv("GAIA_CHROMA_COLLECTION_SUFFIX", "")

# Vector collections not owned by the memory engine (app/constants/memory.py)
# or the files feature (app/constants/files.py).
CHROMA_NOTES_COLLECTION = "notes" + CHROMA_COLLECTION_SUFFIX
CHROMA_CANVAS_COLLECTION = "gaia_canvas" + CHROMA_COLLECTION_SUFFIX

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
