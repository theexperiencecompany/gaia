# API Tests

Test suite for the GAIA FastAPI backend. Covers the full stack from HTTP endpoints down to individual agent nodes, database clients, and background workers.

Tests are organised into four layers that reflect how far they reach into the system:

- **`unit/`** — Pure logic tests. No I/O, no network. External dependencies are mocked so each function or class is tested in isolation.
- **`integration/`** — Wire-up tests. Real production code is imported and executed; only live infrastructure (databases, LLMs, external APIs) is mocked. These catch mis-wiring between components.
- **`e2e/`** — End-to-end scenario tests. A real compiled LangGraph is driven from user input to final state, exercising the full agent loop without any live external services.
- **`composio/`** and **`skills/`** — Live credential tests that hit real third-party APIs. These are skipped in CI unless the relevant secrets are present.

Run the full suite from the `apps/api` directory:

```bash
uv run pytest
```

To run only fast, offline tests:

```bash
uv run pytest -m "unit or integration"
```
