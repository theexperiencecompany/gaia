# Unit Tests

Isolated tests for individual functions, classes, and modules. Nothing here touches a database, network, or file system — all external dependencies are replaced with mocks or in-memory fakes.

The goal is fast feedback: these run in seconds and tell you whether the logic inside a single component is correct, independent of everything around it.

Sub-folders mirror the source layout under `app/`:

| Folder | What it covers |
|--------|---------------|
| `agents/` | Agent graph wiring, state management, routing logic |
| `agents/nodes/` | Individual LangGraph node functions |
| `middleware/` | Agent middleware execution pipeline |
| `models/` | Pydantic schema validation rules |
| `services/` | Business logic inside service classes |
| `skills/` | Skills registry and discovery |
| `tools/` | Tool registry and retrieval |
| `utils/` | Standalone utility functions |
| `workers/` | ARQ background task functions |
