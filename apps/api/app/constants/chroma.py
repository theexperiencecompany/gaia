"""
ChromaDB Constants.

Tunables for the ChromaDB-backed LangGraph store.
"""

# Caps concurrent ChromaDB HTTP connections during a put batch to avoid
# exhausting OS file descriptors (ENFILE 24) when a large batch fans out
# all sockets at once.
MAX_CONCURRENT_CHROMA_WRITES = 10
