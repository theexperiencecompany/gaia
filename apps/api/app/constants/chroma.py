"""
ChromaDB Constants.

Tunables for the ChromaDB-backed LangGraph store.
"""

# Caps concurrent ChromaDB HTTP connections during a put batch to avoid
# exhausting the container's open-file limit (EMFILE 24 — confirmed via
# /proc/1/limits on gaia-backend: RLIMIT_NOFILE soft=1024) when a large batch
# fans out all sockets at once. Upstream callers (chroma_tools_store.py,
# chroma_triggers_store.py) already chunk into batches of 50, so that's the
# real worst case this throttles; the shared chromadb httpx pool tolerates up
# to 100 connections / 40 keepalive, so it isn't the binding constraint.
# Baseline fd usage in prod is ~72, leaving ~950 of headroom, so 20 clears
# even a pile-up of several concurrent batches with a wide margin, while
# still meaningfully throttling below the 50-item batch that caused the
# original crash.
MAX_CONCURRENT_CHROMA_WRITES = 20
