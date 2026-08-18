"""
ChromaDB Constants.

Tunables for the ChromaDB-backed LangGraph store.
"""

# Caps concurrent ChromaDB HTTP connections during a put batch to avoid
# exhausting OS file descriptors (ENFILE 24) when a large batch fans out
# all sockets at once. Upstream callers (chroma_tools_store.py,
# chroma_triggers_store.py) already chunk into batches of 50, so that's the
# real worst case this throttles; the shared chromadb httpx pool tolerates up
# to 100 connections / 40 keepalive, so it isn't the binding constraint.
# 20 matches the pool size we already use for Mongo (maxPoolSize=20) and the
# LangGraph Postgres checkpointer (max_pool_size=20) — same order of
# magnitude as the rest of this process's per-backend concurrency budget,
# while still meaningfully throttling below the 50-item batch that caused
# the original ENFILE crash.
MAX_CONCURRENT_CHROMA_WRITES = 20
