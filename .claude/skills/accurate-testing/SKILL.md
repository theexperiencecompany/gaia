---
name: accurate-testing
description: >
  Write test cases that catch real bugs in production code instead of producing false confidence.
  Use when writing, reviewing, or planning tests for any codebase. Triggers on: "write tests",
  "add test coverage", "test this function", "create unit tests", "integration tests",
  "fix flaky tests", "improve test coverage", "review test quality", "are these tests good",
  "test plan", or any task involving pytest, vitest, jest, or other test frameworks.
  Prevents common AI testing pitfalls: over-mocking, testing frameworks instead of production code,
  fake implementations that bypass real logic, and assertion-free tests.
---

# Accurate Testing

## The Deletion Test (Golden Rule)

Before considering any test complete, apply this mental check:

> If the production code this test targets were deleted entirely, would this test still pass?

If yes, the test is worthless. It tests framework plumbing, not production logic.

## Core Workflow

1. **Identify the production code under test** — find the exact function, class, or endpoint
2. **Read it** — understand its real logic, branches, edge cases, and dependencies
3. **Apply the import rule** — the test file MUST import from production code
4. **Choose the right mock boundary** — mock I/O at the edges, never mock the thing being tested
5. **Write assertions against real behavior** — assert on return values, state changes, side effects that matter
6. **Run the deletion test mentally** — would deleting the production function break this test?

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

## Anti-Pattern Detection

When writing or reviewing tests, check for these red flags. For detailed examples and fixes, see [references/anti-patterns.md](references/anti-patterns.md).

| Red Flag | What It Means |
|----------|--------------|
| Test file has zero imports from `app/` or `src/` | Tests framework, not production code |
| More `@patch` decorators than assertions | Over-mocking — testing your mock setup |
| Test builds its own graph/pipeline from scratch | Tests the framework's graph builder, not your graph |
| Assertions only check `mock.called` or `mock.call_count` | Proves nothing about production behavior |
| Test defines a fake implementation of the thing being tested | Circular — testing your fake, not production code |
| `# mimicking`, `# simplified version of` in comments | Admission that production code is not under test |
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

- [ ] Test imports the production function/class directly
- [ ] Removing the production code would break this test
- [ ] Assertions check return values or state, not just mock calls
- [ ] Each branch in production code has a corresponding test case
- [ ] Error/exception paths are tested
- [ ] Mock count is proportional to external dependencies, not internal logic
- [ ] Test name describes the behavior being verified, not the implementation
