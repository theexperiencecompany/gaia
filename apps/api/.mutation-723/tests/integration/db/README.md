# Integration Tests — Database Clients

Tests for the database client wrappers (`app/db/`) against lightweight in-memory backends. No external server is required — ChromaDB uses `EphemeralClient()`, Redis uses a mock, and the lazy-loader tests use in-process stubs.

The goal is to verify that the wrapper logic (collection management, CRUD operations, caching, vector search) behaves correctly end-to-end, without the overhead of a real server. Schema changes or interface regressions in the wrapper classes will be caught here before they affect the agent layer.
