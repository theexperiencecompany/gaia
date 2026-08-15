# Unit Tests

Isolated tests for individual functions, classes, and modules. Nothing here touches a database, network, or file system — all external dependencies are replaced with mocks or in-memory fakes.

The goal is fast feedback: these run in seconds and tell you whether the logic inside a single component is correct, independent of everything around it.

Sub-folders mirror the source layout under `app/`:

| `tests/unit/` | Mirrors `app/` |
|---------------|----------------|
| `agents/` | `agents/` — graph wiring, state, routing (sub-tiers: `agents/nodes/` → individual node functions) |
| `api/` | `api/v1/endpoints/` + `api/v1/dependencies/` — HTTP contract with the service layer mocked |
| `config/` | `config/` — settings guards, rate limits, model pricing |
| `core/` | `core/` — lazy loader, stream/websocket managers, middleware |
| `db/` | `db/` — client wrappers (mocked clients) |
| `decorators/` | `decorators/` |
| `helpers/` | `helpers/` — agent/email/message helpers |
| `memory/` | `memory/` — ingestion/retrieval logic (mocked engine) |
| `middleware/` | `middleware/` — agent middleware pipeline |
| `models/` | `models/` — Pydantic schema validation rules |
| `override/` | `override/` — langgraph-bigtool integration surface |
| `sandbox/` | `services/sandbox/` + sandbox lifecycle |
| `services/` | `services/` — business logic (repos mocked, incl. `services/hil/`, `services/onboarding/`) |
| `skills/` | `agents/skills/` — registry and discovery |
| `storage/` | `services/storage/` — JuiceFS, sessions, workspace VFS |
| `tools/` | `agents/tools/` — tool registry and retrieval (incl. `tools/coding/`) |
| `utils/` | `utils/` |
| `workers/` | `workers/` — ARQ background task functions |

Conventions and the quality bar live in `../CLAUDE.md`. Scaffolds to copy from: `../_template/`.
