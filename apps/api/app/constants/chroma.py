"""ChromaDB collection naming, shared by every feature that owns a collection.

One Chroma process can be shared by several concurrent test lanes (see
scripts/ci/test-services.sh), and Chroma has no database/namespace
concept — collections are a single flat namespace per server. So the *name* is
the namespace: GAIA_CHROMA_COLLECTION_SUFFIX is appended to every
collection GAIA creates, which is what keeps lane r0's notes_r0 from
being wiped by lane r1's teardown.

The suffix also predates that use: it separates runs that embed with different
models/dimensions, which cannot share a collection. Empty (the default) is the
production naming, so unset envs reproduce the historical names byte for byte.

Also holds tunables for the ChromaDB-backed LangGraph store.
"""

import os

from app.constants.cache import ONE_HOUR_TTL

CHROMA_COLLECTION_SUFFIX = os.getenv("GAIA_CHROMA_COLLECTION_SUFFIX", "")

# Vector collections not owned by the memory engine (app/constants/memory.py)
# or the files feature (app/constants/files.py).
CHROMA_NOTES_COLLECTION = "notes" + CHROMA_COLLECTION_SUFFIX
CHROMA_CANVAS_COLLECTION = "gaia_canvas" + CHROMA_COLLECTION_SUFFIX

# Caps concurrent ChromaDB HTTP connections process-wide (see
# loop_bound_semaphore in chroma_store.py) to avoid EMFILE 24. RLIMIT_NOFILE
# soft limit is 1024 with ~72 fds baseline, so 20 clears it with wide margin.
MAX_CONCURRENT_CHROMA_WRITES = 20

# Bounded retry for the shared Gemini embeddings provider (see
# app/db/chroma/resilient_embeddings.py). A transient Vertex 429 (per-minute
# quota for gemini-embedding) or 5xx on an embed call is retried with exponential
# backoff so a quota blip costs latency rather than failing tool discovery for
# the whole turn. Kept small: three attempts over a few seconds is enough to ride
# out a per-minute-quota blip without stalling a user-blocking tool call.
EMBEDDING_RETRY_MAX_ATTEMPTS = 3
EMBEDDING_RETRY_BASE_DELAY_SECONDS = 0.5
EMBEDDING_RETRY_MAX_DELAY_SECONDS = 4.0

# How long a namespace's indexed-signature marker survives in Redis. It is a
# fast-path hint only (the ChromaDB hash diff is the source of truth), so a day
# is plenty — a stale or missing marker just costs one extra diff read.
TOOLS_INDEX_CACHE_TTL_SECONDS = 86_400

# Cross-replica seed lock: on a cold/wiped Chroma, every replica would
# otherwise embed the full catalog at once (N x embedding cost). A follower
# that can't acquire within the window falls back to running the idempotent seed unsynchronized.
TOOLS_SEED_LOCK_KEY_PREFIX = "lock:chroma:tools-seed:"
TOOLS_SEED_LOCK_LEASE_SECONDS = 30
TOOLS_SEED_LOCK_RENEW_SECONDS = 10
TOOLS_SEED_LOCK_ACQUIRE_TIMEOUT_SECONDS = 120
# Hard cap on renewal: past this the lease expires so a wedged seed can't block
# every replica's indexing forever. Well above the real embedding time (the
# ~1.6k-tool catalog batches in a minute or two).
TOOLS_SEED_LOCK_MAX_HOLD_SECONDS = 300

# The gaia_knowledge corpus snapshot is reloaded after this long. In-process
# writes drop the snapshot directly; a re-populate from the offline script is a
# separate process and is picked up within this TTL, the cross-process bound.
GAIA_KNOWLEDGE_SNAPSHOT_TTL_SECONDS = ONE_HOUR_TTL
