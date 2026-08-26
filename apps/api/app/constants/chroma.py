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

# Native output width of models/gemini-embedding-001 (app/agents/tools/core/store.py),
# which embeds every vector in the tools and triggers collections. ChromaDB pins a
# collection's dimensionality from the first vectors written to it, so this must match
# the model or every later write is rejected with InvalidArgumentError. Distinct from
# EMBEDDING_DIM (app/constants/memory.py) — that is the memory subsystem's own model.
GEMINI_EMBEDDING_DIM = 3072
