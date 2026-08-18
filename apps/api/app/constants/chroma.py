"""
ChromaDB Constants.

Tunables for the ChromaDB-backed LangGraph store.
"""

# Caps concurrent ChromaDB HTTP connections during a put batch to avoid
# EMFILE 24 (per-process fd limit, not system-wide ENFILE). gaia-backend's
# RLIMIT_NOFILE soft limit is 1024 with ~72 fds baseline usage, so 20 clears
# it with wide margin while still throttling below the 50-item worst-case batch.
MAX_CONCURRENT_CHROMA_WRITES = 20
