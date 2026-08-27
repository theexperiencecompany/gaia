---
name: accurate-testing
description: >
  Write adversarial test cases that break production code instead of producing false confidence.
  Use when writing, reviewing, or planning tests for any codebase. Triggers on: "write tests",
  "add test coverage", "test this function", "create unit tests", "integration tests",
  "fix flaky tests", "improve test coverage", "review test quality", "are these tests good",
  "test plan", "break this code", "find edge cases", or any task involving pytest, vitest, jest,
  or other test frameworks.
  Enforces the prime directive — a test that cannot fail is not a test — and prevents common AI
  testing pitfalls: over-mocking, testing frameworks instead of production code, fake
  implementations that bypass real logic, and assertion-free tests.
---

# Accurate Testing

## Prime Directive: Tests Exist to Break the Code

A test is not a certificate that the code works. It is an **attack** on the code. You are not the
author defending the implementation — you are the adversary trying to make it produce a wrong
answer, crash, corrupt state, or silently do nothing.

The bar is not "the test passes." The bar is:

> **If the implementation were wrong, would this test catch it?**

If a test cannot fail, it is not a test. It is decoration that makes the suite look green while
bugs ship. Green-on-first-write is a **smell**, not a success — it usually means the test was
written to mirror what the code already does, so it can only ever agree with it.

Three consequences follow, and they are non-negotiable:

1. **Every test must be falsifiable.** There must exist a plausible bug that turns it red.
2. **Prove falsifiability — don't assume it.** Break the code and watch the test fail (see the
   Mutation Check below). A test you never saw fail is an unverified claim.
3. **Write tests against the code's blind spots, not its happy path.** After building a feature,
   the job is to hunt the scenarios the implementation *forgot to handle* — not to re-enact the
   ones it obviously handles.

## The Mutation Check (The Real Bar)

After writing a test, **deliberately break the production code** and re-run it. The test must go
red. If it stays green, the test is worthless — delete or rewrite it.

Pick a mutation that mirrors a bug a real engineer would ship:

| Mutation | Catches |
|----------|---------|
| Flip a comparison (`>` → `>=`, `==` → `!=`) | Off-by-one and boundary bugs |
| Invert a condition (`if x` → `if not x`) | Branch routing bugs |
| Delete a validation / guard clause | Missing input rejection |
| Return a constant instead of the computed value | Assertions that don't check the real output |
| Swap two arguments at a call site | Positional-argument mixups |
| Remove an `await` / drop the error handler | Async and failure-path bugs |
| Delete the function body entirely (`return None`) | The Deletion Test — the weakest gate |

Then **restore the code** and confirm the suite is green again. Red-on-broken plus green-on-fixed
is the only evidence that a test is real. Never leave a mutation in the working tree.

## The Deletion Test (Minimum Gate)

The cheapest mutation, applied mentally before you even run anything:

> If the production code this test targets were deleted entirely, would this test still pass?

If yes, the test is worthless — it exercises framework plumbing, not production logic. Passing the
Deletion Test is necessary but **not sufficient**: a test can import the real function, exercise it,
and still be blind to every bug in it. The Mutation Check is the real bar.

## Core Workflow

1. **Identify the production code under test** — find the exact function, class, or endpoint
2. **Read it** — understand its real logic, branches, edge cases, and dependencies
3. **Hunt the gaps first** — before writing a single assertion, enumerate what the code *forgot to
   handle*: unvalidated inputs, unhandled failure modes, boundaries, concurrent access, partial
   writes. See [references/breaking-the-code.md](references/breaking-the-code.md). These gaps are
   the test plan.
4. **Apply the import rule** — the test file MUST import from production code
5. **Choose the right mock boundary** — mock I/O at the edges, never mock the thing being tested
6. **Write assertions against real behavior** — assert on return values, state changes, side effects
   that matter. Assert what the code *should* do, derived from the requirement — never what it
   currently happens to return.
7. **Run the Mutation Check** — break the code, watch the test go red, restore the code, watch it go
   green. A test you have not seen fail is not yet a test.

## When a Test Finds a Bug, That Is Success

An adversarial test that goes red on correct-looking production code has done its job. Do not soften
the test to make it pass, do not relax the assertion, do not mark it `xfail`/`skip` to get to green.
Report the failure with the evidence and fix the production code at the root. The suite going green
by weakening the tests is the exact failure mode this skill exists to prevent.

## The Five Laws of Accurate Tests

### Law 1: Import Production Code

Every test file must import the actual production function/class it claims to test.

```python
# WRONG — tests LangGraph, not your app
from langgraph.graph import StateGraph
graph = StateGraph(MessagesState)
graph.add_node("echo", lambda s: {"messages": [AIMessage(content="Echo")]})

# RIGHT — tests your app
from app.agents.core.graph_builder.build_graph import build_comms_agent
graph = build_comms_agent(checkpointer=MemorySaver())
```

### Law 2: Mock at the Boundary, Not the Core

Mock external I/O (network, database, filesystem). Never mock the logic under test.

```python
# WRONG — mocks the function being tested, tests nothing
with patch("app.services.chat_service.run_chat_stream") as mock:
    mock.return_value = "response"
    result = run_chat_stream(msg)  # just calls the mock

# RIGHT — mocks the dependency, tests the real function
with patch("app.services.chat_service.llm_client.invoke") as mock_llm:
    mock_llm.return_value = AIMessage(content="hello")
    result = run_chat_stream(msg)  # runs real logic, fake LLM
```

**Law 2b: Patch Module Singletons, Not Individual Functions**

When production code uses a module-level singleton (a shared client, cache, or connection object), patch the singleton's attribute directly. This ensures all production code that touches the singleton — including code several layers deep — uses the real test resource without any function-level patching.

```python
# Production: redis_cache = RedisCache()  (module singleton)
# StreamManager uses redis_cache.redis internally

# WRONG — patches one function, misses all others that use redis_cache
with patch("app.core.stream_manager.StreamManager.publish_chunk") as mock:
    ...  # other methods still use the broken/missing redis_cache.redis

# RIGHT — patch the singleton attribute; all production code sees real Redis
from app.db.redis import redis_cache

@pytest.fixture
async def real_redis(monkeypatch):
    client = Redis.from_url("redis://localhost:6379", decode_responses=True)
    await client.ping()
    monkeypatch.setattr(redis_cache, "redis", client)   # one patch, everything works
    yield client
    await client.flushdb()
    await client.aclose()

async def test_stream_publishes(real_redis):
    await StreamManager.start_stream("s1", "conv1", "user1")
    await StreamManager.publish_chunk("s1", "data: hello\n\n")
    chunks = []
    async for chunk in StreamManager.subscribe_stream("s1"):
        chunks.append(chunk)
        break
    assert chunks[0] == "data: hello\n\n"
```

### Law 3: Assert on Production Behavior

Assert on what the production code actually does — return values, state mutations, raised exceptions, emitted events.

```python
# WRONG — asserts mock was called (tests your test setup)
mock_service.process.assert_called_once_with(data)

# RIGHT — asserts the actual outcome
result = process_email(raw_email)
assert result.subject == "Re: Meeting"
assert result.is_read is False
assert len(result.attachments) == 2
```

### Law 4: Cover Real Branches

Read the production code. Find the `if/elif/else`, `try/except`, and early returns. Write a test for each path.

```python
# Production code has: if user.is_premium: ... else: ...
# Test BOTH paths
def test_premium_user_gets_extended_features(): ...
def test_free_user_gets_basic_features(): ...
```

### Law 5: Test Error Paths, Not Just Happy Paths

Production bugs cluster in error handling. Test what happens when dependencies fail.

```python
def test_handles_api_timeout():
    with patch("app.tools.gmail.client.send") as mock:
        mock.side_effect = httpx.TimeoutException("timeout")
        result = send_email(to="x@y.com", body="hi")
        assert result.error == "Failed to send: timeout"
```

## Scenario Hunt: Attack What the Code Forgot to Handle

Coverage of the branches that *exist* is the floor, not the ceiling. Law 4 tests the `if/else` the
author wrote. The bugs live in the cases the author never wrote a branch for.

After a feature is built, go hunting. For every input, dependency, and piece of state the code
touches, ask: **what value or timing would this code not survive?** Then write that test.

| Attack surface | Ask |
|----------------|-----|
| **Inputs** | Empty, null/`None`, zero, negative, unicode, whitespace-only, absurdly long, wrong type, malformed? |
| **Boundaries** | First, last, one-below, one-above, exactly-at the limit? Empty collection, single element? |
| **Failure modes** | Dependency times out, returns an error, returns garbage, returns `None`, raises mid-iteration? |
| **State** | Called twice, called out of order, called after failure, called on a half-written record? |
| **Authorization** | Another user's ID, a revoked token, a resource that no longer exists? |
| **Volume** | Duplicates, pagination edges, a payload larger than any assumed limit? |

Each row that the production code does not survive is either a **bug to fix** or a **requirement to
make explicit**. Both outcomes are wins. The full playbook, with per-type checklists and worked
examples, is in [references/breaking-the-code.md](references/breaking-the-code.md).

## Anti-Pattern Detection

When writing or reviewing tests, check for these red flags. For detailed examples and fixes, see [references/anti-patterns.md](references/anti-patterns.md).

| Red Flag | What It Means |
|----------|--------------|
| The test cannot be made to fail by any plausible bug | Not a test — it is decoration |
| Test was never observed failing (no Mutation Check run) | Falsifiability is an unverified claim |
| Assertion was written by reading the code's current output | Tests what the code *does*, so it can never disagree with it |
| Suite is 100% happy-path | The bugs are in the paths you didn't write |
| A failing test was relaxed, `skip`ped, or `xfail`ed to get to green | Suppressing the bug, not fixing it |
| Test file has zero imports from `app/` or `src/` | Tests framework, not production code |
| More `@patch` decorators than assertions | Over-mocking — testing your mock setup |
| Test builds its own graph/pipeline from scratch | Tests the framework's graph builder, not your graph |
| Assertions only check `mock.called` or `mock.call_count` | Proves nothing about production behavior |
| Test defines a fake implementation of the thing being tested | Circular — testing your fake, not production code |
| `# mimicking`, `# simplified version of` in comments | Admission that production code is not under test |
| Test manually reimplements what a production function does | Duplication — if you delete the function, test still passes |
| All tests pass when production code is broken | The entire suite is false confidence |

## Mock Hierarchy (What to Mock Where)

| Test Type | Mock | Don't Mock |
|-----------|------|------------|
| **Unit** | DB clients, HTTP clients, message queues, filesystem | The function under test, its direct logic |
| **Integration** | LLM API calls, external SaaS APIs (Composio, Stripe) | Your service layer, your DB queries, your routing |
| **E2E** | LLM (use fake model), external APIs (use recorded responses) | Your entire pipeline — graph, routing, services, DB |

## Language-Specific Guidance

- **Python (pytest)**: See [references/pytest-patterns.md](references/pytest-patterns.md) for fixture design, parametrize patterns, and conftest hierarchy
- **TypeScript (vitest/jest)**: See [references/vitest-patterns.md](references/vitest-patterns.md) for module mocking, type-safe mocks, and async patterns

## Pre-Commit Checklist

Before finalizing any test:

- [ ] **I broke the production code and watched this test fail, then restored it and watched it pass**
- [ ] I can name the specific bug this test would catch
- [ ] Assertions come from the requirement, not from the code's current output
- [ ] Test imports the production function/class directly
- [ ] Removing the production code would break this test
- [ ] Assertions check return values or state, not just mock calls
- [ ] Each branch in production code has a corresponding test case
- [ ] Error/exception paths are tested — the suite is not all happy-path
- [ ] The Scenario Hunt ran: boundaries, bad inputs, dependency failures, out-of-order calls
- [ ] No test was weakened, skipped, or `xfail`ed to turn the suite green
- [ ] No mutation was left behind in the production code
- [ ] Mock count is proportional to external dependencies, not internal logic
- [ ] Test name describes the behavior being verified, not the implementation
