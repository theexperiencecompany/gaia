# Testing GAIA (apps/api)

The bar for a test here is not "it passes." It is: **if the production code it covers
breaks, this test fails.** A green test that survives its target being deleted is worse
than no test — it is false confidence. This file is how we keep that from happening.

## The one question that decides if a test is good

> If I delete (or corrupt) the production code this test targets, does the test fail?

If no, the test is worthless. We make this objective with **mutation testing**: inject a
single semantic bug into the production function (flip `==`/`!=`, change a constant,
drop a return, swap a branch) and confirm a test goes red. The fraction of injected bugs
caught is the **kill rate** — the real quality score. An LLM's opinion ("this looks
thorough") is not a score; we measured a test an LLM rated "SOLID" that killed only 24%.

Mutation harness: `.agents/plans/test-overhaul/mutate.py` (gitignored tooling).
```bash
# scope to the functions under test so "all mutants" stays bounded
/Users/aryan/Projects/GAIA/gaia/.venv/bin/python .agents/plans/test-overhaul/mutate.py \
    app/services/foo.py --tests tests/unit/services/test_foo.py \
    --target-name foo_fn --root . --quiet
```
Target: **≥90% kill** for normal code, **100% for critical-path** (streaming, agent
graph, auth, payments, persistence). Every surviving mutant must be a *proven* equivalent
(behaviour-preserving), documented in the test's spec block — not an unexplained gap.

## Write the behavior spec first

Before touching assertions, write the contract as the test module docstring:
```
UNIT: app/.../foo.py :: foo_fn
EXPECTED: what the function promises the caller / the system.
MECHANISM: how it does it (the calls, the branches, what it streams/persists).
MUST-CATCH: one line per branch, error path, and external contract that, if broken,
            must turn a test red (streamed keys, DB filters, status codes, return shape).
EQUIVALENT MUTANTS: any survivors that cannot change behaviour, with proof.
```
Each MUST-CATCH maps to ≥1 test and ≥1 killed mutant. This is "what's expected / what
actually happens / what must be caught if broken" — the spec the suite is built around.

## The five laws

1. **Import the real unit.** The test file imports the production function/class it tests.
   Never re-implement or fork production logic in the test.
2. **Mock only at I/O boundaries** (network, DB, queue, SaaS, LLM). Never mock the function
   under test or an internal collaborator whose output you assert. Prefer patching the
   module's own binding (`app.services.foo.collection`) or a singleton attribute
   (`redis_cache.redis`) over individual functions.
3. **Assert real behaviour** — return values, state mutations, raised exceptions, emitted/
   streamed payloads. Never assert *only* `mock.assert_called` / `call_count`.
4. **Cover every branch and every error path** — `if/elif/else`, `try/except`, early
   returns, and the failure of each mocked dependency.
5. **Be deterministic and isolated** — no `datetime.now()`-baked literals, no test ordering
   dependence, no shared mutable state. Passes alone (`-n0`) AND in parallel (`-n4`).

## Banned (auto-reject)

- Asserting against a value the test itself defined / a fake re-implementation.
- `assert x or y` to tolerate two shapes; substring oracles that also match boilerplate
  (`"TD" in prompt`); `assert True`; assertion-free "doesn't raise" as the only check for
  code with real logic.
- Spying on the object's own method, mocking it away, asserting it was called (tautology).
- Building a toy `StateGraph`/pipeline inline and testing that instead of the real builder.
- Hardcoded-count snapshots (`assert len(x) == 47`) as a behaviour test.
- Testing a third-party library (`langgraph.add_messages`, `redis.incr`) as if it were ours.
- Hardcoded dates (`"Nov 21, 2024"`) — they rot. Freeze time or assert relative.

## Fewer, stronger

Quality over quantity. Each retained test should kill ≥1 mutant no sibling test kills.
Delete redundant and hollow tests rather than accumulating them. A file with 30 shallow
tests at 50% kill is worse than 9 sharp tests at 95%.

## How to run (this project's specifics)

- **Use the venv python directly**, never `uv run` in loops/parallel (it triggers a sync):
  `.venv/bin/python -m pytest tests/unit/... -q`.
- `asyncio_mode = auto` — async tests need no `@pytest.mark.asyncio` on the function, but a
  test *class* needs the marker (or per-test markers) under strict mode.
- Default `addopts`: `-m "not composio" --strict-markers -n 4`. Use `-n0` to reproduce a
  single test in isolation (catches order/shared-state bugs).

### Tiers
- `tests/unit/` — mock every external dependency at the boundary. Fast, no real services.
- `tests/service/`, `tests/integration/` — **real** Postgres/Redis/Mongo/Chroma. Locally set
  `MONGODB_URL=mongodb://localhost:27017/gaia_test`; in CI the Dagger container provides them.
  Use the fixtures in `tests/service/conftest.py` (`mongodb_url`, `conversations_collection`,
  `real_redis`, `make_conversation`) — resolve URLs from the fixture, monkeypatch the target
  module's *own* collection bindings, seed with `uuid4` IDs, and delete in teardown.
- `tests/e2e/` — marked `e2e`, near-real services, run separately.
- `tests/composio/` — need real credentials, excluded by default.

### conftest gotchas
- Root `conftest.py` sets `ENV=development` before any app import and globally patches
  external SaaS (Infisical, payment status, rate limiter). It mocks Mongo only when
  `USE_REAL_SERVICES != "1"` (default is `"1"`).
- The `providers` registry is a global singleton never reset between tests — use unique
  provider names (UUID suffixes) to avoid cross-test pollution.
- Fake credentials in tests trip `detect-secrets`; mark them `# pragma: allowlist secret`.

## Definition of done for a test file

- [ ] Behaviour spec written for every unit it covers
- [ ] Imports the real unit; mocks only at boundaries; asserts real behaviour
- [ ] Every branch + error path covered; no banned anti-patterns
- [ ] Green isolated (`-n0`) AND parallel (`-n4`), deterministic across repeats
- [ ] Mutation kill ≥ gate; every survivor a proven, documented equivalent
- [ ] `ruff check` clean
