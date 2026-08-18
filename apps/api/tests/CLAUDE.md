# API Test Conventions

One doc, read before writing any test. Enforcement lives in the lints and `tests/meta/` invariants — this is the *why*, not the full rulebook.

**What we coded should work — prove it.**

## Tiers

| Tier | Where | Needs to run | Add a test there when |
|---|---|---|---|
| Unit | `tests/unit/` (mirrors `app/`) | nothing — mocked, hermetic, no I/O | new service fn → `unit/services/`; new endpoint → `unit/api/` |
| Integration | `tests/integration/` | nothing — real production code, mocked infra | wiring between components, full request cycle |
| Real-infra | `tests/integration/real/` (incl. `real/memory/`) | Docker + `USE_REAL_SERVICES=1` — otherwise the whole tier skips at collection (milliseconds, never a hang) | behavior only provable against real Postgres/Redis/Mongo |
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
| Hermetic default (no Docker, no network) | `nx test api` — every tier that runs offline; real-infra/contracts/HIL skip at collection |
| Real-infra tier (docker compose up + opt-in) | `nx run api:test:real` — `tests/integration/real/` + contracts + HIL e2e |
| Specialized | `nx run api:test:stress` · `nx run api:test:meta` · `nx run api:test:composio` |

`mise run test:python:hermetic` and `mise run test:python:real` mirror the two
tiers. Fast-suite invariant: the hermetic default must finish within the CI
`test-fast` lane's budget (~4 min); never slow it down — real-infra behavior
belongs in `test:real`, not in the default run.

## Structure

- **AAA**: arrange, act, assert — one behavior per test, in one paragraph.
- **Naming**: mirror the module under test; bug regressions carry the issue number.
- **Bug regressions carry `@pytest.mark.regression`.** CI re-runs the marked
  tests a PR *adds* against the base revision and fails if any of them PASSES
  there — a test that is green without its fix does not pin the bug it claims
  to. Mark only the tests that go red without the fix, not the whole file; the
  gap-fill tests alongside them legitimately pass on base. Once merged, a marked
  test stays marked and is not re-proven by later PRs that touch the file.
- **The mark needs a module that exists on base.** The lane counts an ERROR as
  "did not prove anything", not as proof — a test that never reached its
  assertions shows the harness broke, not that the bug is caught. So the mark
  works when only a *symbol* is new (the `AttributeError` fires inside the test
  body and registers as a FAILURE), and breaks when the whole *module* is new
  (the file cannot be imported on base, so it fails at collection and the lane
  rejects it). Tests for a brand-new module are gap-fill: leave them unmarked.
  The two cases look identical until CI fails, so check with
  `git cat-file -e origin/master:<path>` before reaching for the mark.
- **Hermetic paths**: never hardcode `~` or absolute paths — the `_hermetic_environment` fence owns env (it blanks real credentials at session start); any env a test needs is provisioned by fixtures, not read from the developer's machine.
- **Fixtures catalog** — search before you build:
  - `tests/conftest.py` — env fence, `client` / `unauthed_client` (ASGITransport), `fake_user` / `fake_user_2`
  - `tests/helpers.py` — `create_fake_llm`, `create_fake_llm_with_tool_calls`, auth middlewares, `worker_redis_url` / `worker_mongo_db_name`
  - `tests/factories.py` — `make_user`, `make_conversation`, `make_state`, `make_config`
  - `tests/unit/conftest.py` — `mock_mongodb`, `mock_redis`
  - `tests/e2e/_harness/graph_run.py` — `RecordingFakeModel` (`last_chat_messages`, `chat_messages_log`), `CallAllToolsModel`, `comms_graph` / `executor_graph`, `run_graph`, `GraphRun`
  - `tests/integration/real/db_fixtures.py` — `mongodb_url`, `redis_url`, `postgres_url`, `mongo_db`, `real_redis` (shared by e2e and real-infra suites)
- **Copy-from-me scaffolds** live in `tests/_template/` (`_service_example.py`, `_endpoint_example.py`) — underscore-prefixed so pytest never collects them; copy and rename.

## Environment & hermeticity

The `_hermetic_environment` session fixture (root `conftest.py`) guarantees no
test can use a real credential: it blanks every env var matching
`(API_KEY|TOKEN|SECRET|_KEY|_SECRET)` at session start — a developer's `.env`
or shell can never leak a live key into a test run, so the suite is
deterministic and can never bill a real API.

Exceptions are explicit declarations, never accidents:

- The harness's own fake values (`WORKOS_API_KEY`, `MCP_ENCRYPTION_KEY`,
  `AGENT_SECRET`, `GOOGLE_API_KEY` fake) survive by allowlist.
- A live-credential tier declares the keys it legitimately needs by setting
  `HERMETIC_ALLOW_KEYS` (comma-separated) in its conftest at import time —
  e.g. `tests/composio/conftest.py` declares `COMPOSIO_KEY,
  COMPOSIO_WEBHOOK_SECRET`; `tests/model_onboarding/conftest.py` declares
  `OPENROUTER_API_KEY`. Nothing else survives the fence.

Never hardcode real secrets in tests; never read a `~` path (the fence owns
env, fixtures own paths). If a test needs a key, declare it via
`HERMETIC_ALLOW_KEYS` in the tier's conftest — with a comment saying why the
live value is genuinely required.
