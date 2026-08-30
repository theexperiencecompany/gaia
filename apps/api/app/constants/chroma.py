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
