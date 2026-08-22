# API Tests

Test suite for the GAIA FastAPI backend. Covers the full stack from HTTP endpoints down to individual agent nodes, database clients, and background workers.

Tests are organised into layers that reflect how far they reach into the system:

- **`unit/`** — Pure logic tests. No I/O, no network. External dependencies are mocked so each function or class is tested in isolation.
- **`integration/`** — Wire-up tests. Real production code is imported and executed; only live infrastructure (databases, LLMs, external APIs) is mocked. These catch mis-wiring between components.
- **`integration/real/`** — Real-database tests. Production functions run unmodified against real Redis/Postgres/MongoDB/ChromaDB (see `integration/real/README.md`), not mocks. The memory-engine suite lives in `integration/real/memory/`. Run via `nx run api:test:real`.
- **`contracts/`** — Repository contract tests against real (or ephemeral) databases. Verify that every repository honors the shared `MongoRepository` base contract. Run via `nx run api:test:contracts`.
- **`e2e/`** — End-to-end scenario tests (marked `e2e`, require live or near-real services, not cached). A real compiled LangGraph is driven from user input to final state. Run via `nx run api:test:e2e`.
- **`composio/`** — Live-credential tests against the Composio API. Excluded from the default suite (`-m "not composio"`); require real credentials.
- **`model_onboarding/`** — Live model capability checks, run when adding a model (bills real tokens). Excluded from the default suite.

Also present: `meta/` (test-infra checks) and `stress/` (slow, resource-heavy load tests).

Run the full default suite (unit + integration) from the `apps/api` directory:

```bash
uv run pytest tests/unit tests/integration
```

To run only fast, offline tests:

```bash
uv run pytest tests/unit
```
