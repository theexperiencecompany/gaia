# Unit Tests — Tools

Tests for the tool registry and retrieval layer (`app/agents/tools/core/`). The registry is the central store that maps tool names to callable implementations; the retrieval layer uses ChromaDB embeddings to surface relevant tools for a given query.

Tests verify that tools can be registered, looked up by name, and that the retrieval function returns the right subset given a mocked vector store. The ChromaDB client is replaced with a mock so no embedding model or database is needed.
