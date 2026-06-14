"""Embedding + reranking sidecar.

One process loads the fastembed models once and serves embed/rerank over HTTP
so every app process (API, ARQ worker) shares a single copy of the weights
instead of each loading its own ~1.8 GB. See ``server.py`` for the service and
``app.memory.embeddings`` for the client that calls it when configured.
"""
