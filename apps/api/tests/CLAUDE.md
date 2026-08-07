# API Test Conventions

One doc, read before writing any test. Enforcement lives in the lints and `tests/meta/` invariants — this is the *why*, not the full rulebook.

**What we coded should work — prove it.**

## Tiers

| Tier | Where | Needs to run | Add a test there when |
|---|---|---|---|
| Unit | `tests/unit/` (mirrors `app/`) | nothing — mocked, hermetic, no I/O | new service fn → `unit/services/`; new endpoint → `unit/api/` |
| Integration | `tests/integration/` | nothing — real production code, mocked infra | wiring between components, full request cycle |
| Real-infra | `tests/integration/real/` (incl. `real/memory/`) | Docker + `USE_REAL_SERVICES=1` | behavior only provable against real Postgres/Redis/Mongo |
| Contracts | `tests/contracts/` | real Mongo + Redis | repository contract changes (never mocks) |
| E2E | `tests/e2e/` | real compiled graphs + fake LLM (`_harness/`), offline | user journey through the compiled graph |
| Stress | `tests/stress/` | none — in-process fakes, no sleeps | race/retry/idempotency invariants |
| Meta | `tests/meta/` | nothing | import fences, architecture invariants |
| Live opt-in | `tests/composio/`, `tests/model_onboarding/` | real credentials | composio creds; model capability checks (bills tokens) |

A bug ships a failing-then-passing test in the *natural* file for the tier that catches it, named `test_<subject>_<issue>.py` (e.g. `test_stream_manager_4921.py`).

## Quality bar

1. **Can it fail?** If deleting a line of product code can't make it red, it's theater.
2. **Behavior, not implementation.** Assert outcomes and contract, never internal call order.
3. **Includes the failure path.** The error branch is behavior too.
4. **Not a duplicate.** If a tier already proves it, extend there — don't re-prove it in a new file.
5. **No theater.** Never mock the thing under test — mock its seams (repositories, clients). A caller mocking a service means that service's logic has never run: un-mock it instead.
6. **Deterministic.** No real sleeps, no wall-clock races, no machine-speed dependence.
7. **No LLM-prose asserts.** Assert on structure, tool calls, and state — never on generated sentence text.

## Run it

| What | Command |
|---|---|
| Fast local (hermetic, no Docker) | `nx test api` — unit + integration only |
| Real infra (Docker up + `USE_REAL_SERVICES=1`) | `nx run api:test:e2e` · `nx run api:test:service` · `nx run api:test:contracts` |
| Specialized | `nx run api:test:stress` · `nx run api:test:meta` |

Never run a raw full `pytest` locally — the targets pin the dirs, markers, and exclusions (`-m "not composio and not model_onboarding"`, xdist, timeout). A raw run drags in live-credential and real-infra suites.

## Structure

- **AAA**: arrange, act, assert — one behavior per test, in one paragraph.
- **Naming**: mirror the module under test; bug regressions carry the issue number.
- **Hermetic paths**: never hardcode `~` or absolute paths — the `_hermetic_environment` fence owns env (it blanks real credentials at session start); any env a test needs is provisioned by fixtures, not read from the developer's machine.
- **Fixtures catalog** — search before you build:
  - `tests/conftest.py` — env fence, `client` / `unauthed_client` (ASGITransport), `fake_user` / `fake_user_2`
  - `tests/helpers.py` — `create_fake_llm`, `create_fake_llm_with_tool_calls`, auth middlewares, `worker_redis_url` / `worker_mongo_db_name`
  - `tests/factories.py` — `make_user`, `make_conversation`, `make_state`, `make_config`
  - `tests/unit/conftest.py` — `mock_mongodb`, `mock_redis`
  - `tests/e2e/_harness/graph_run.py` — `RecordingFakeModel` (`last_chat_messages`, `chat_messages_log`), `CallAllToolsModel`, `comms_graph` / `executor_graph`, `run_graph`, `GraphRun`
  - `tests/integration/real/db_fixtures.py` — `mongodb_url`, `redis_url`, `postgres_url`, `mongo_db`, `real_redis` (shared by e2e and real-infra suites)
- **Copy-from-me scaffolds** live in `tests/_template/` (`_service_example.py`, `_endpoint_example.py`) — underscore-prefixed so pytest never collects them; copy and rename.
