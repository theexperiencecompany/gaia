"""GAIA Memory — custom local memory engine.

Write-heavy / read-cheap: all LLM work happens asynchronously at ingestion
time; recall makes zero LLM calls. PostgreSQL is the canonical store,
ChromaDB holds dense vectors, embeddings are computed locally via fastembed.
"""
