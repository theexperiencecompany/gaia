# Anti-Patterns: False Confidence in Tests

## Table of Contents

1. [Fake Implementation](#1-fake-implementation)
2. [Framework Testing](#2-framework-testing)
3. [Over-Mocking](#3-over-mocking)
4. [Echo Graph Testing](#4-echo-graph-testing)
5. [Assertion-Free Tests](#5-assertion-free-tests)
6. [Mock-Assertion Tests](#6-mock-assertion-tests)
7. [Hardcoded Response Tests](#7-hardcoded-response-tests)
8. [Missing Error Path Coverage](#8-missing-error-path-coverage)
9. [Shared State Leaks](#9-shared-state-leaks)
10. [Test Category Misuse](#10-test-category-misuse)

---

## 1. Fake Implementation

**Pattern**: Test defines its own version of the thing being tested instead of importing production code.

```python
# ANTI-PATTERN
# test_send_email_flow.py
def fake_send_email(to: str, subject: str, body: str) -> str:
    return f"Email sent to {to}"  # hardcoded success

async def test_send_email():
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([fake_send_email]))
    # ... tests that fake_send_email returns "Email sent to X"
```

**Why it's dangerous**: The real `send_email` tool handles OAuth, rate limits, attachment encoding, CC/BCC, HTML sanitization. None of that is tested. A bug in any of those areas passes CI green.

**Fix**: Import the real tool and mock only its HTTP layer.

```python
from app.agents.tools.composio.gmail import gmail_send_email

async def test_send_email():
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(200, json={"id": "msg_123"})
        result = await gmail_send_email(to="x@y.com", subject="Hi", body="Hello")
        assert result["id"] == "msg_123"
```

---

## 2. Framework Testing

**Pattern**: Test constructs a framework object (StateGraph, Router, Pipeline) from scratch and tests framework behavior.

```python
# ANTI-PATTERN
def test_tool_routing():
    graph = StateGraph(MessagesState)
    graph.add_node("agent", lambda s: {"messages": [AIMessage(content="ok")]})
    graph.add_node("tools", ToolNode([some_tool]))
    graph.add_conditional_edges("agent", tools_condition)
    app = graph.compile()
    # This tests that LangGraph's tools_condition routes to ToolNode.
    # It does NOT test your app's routing logic.
```

**Why it's dangerous**: LangGraph already tests its own `tools_condition`. Duplicating this proves LangGraph works, not that your `should_continue` function or custom routing works.

**Fix**: Import the real compiled graph from production.

```python
from app.agents.core.graph_builder.build_graph import build_comms_agent

def test_tool_routing():
    agent = build_comms_agent(checkpointer=MemorySaver())
    # Now tests YOUR graph with YOUR nodes, YOUR routing, YOUR tools
```

---

## 3. Over-Mocking

**Pattern**: Test has more `@patch` lines than lines of actual test logic. Everything is mocked so nothing real executes.

```python
# ANTI-PATTERN — 13 patches, testing that mocks get called
@patch("app.mcp.client.BaseMCPClient")
@patch("app.mcp.client.oauth_token_refresh")
@patch("app.mcp.client.create_session")
@patch("app.mcp.client.get_tools")
@patch("app.mcp.client.cache_store")
@patch("app.mcp.client.validate_transport")
@patch("app.mcp.client.get_server_config")
@patch("app.mcp.client.emit_status")
@patch("app.mcp.client.dedup_lock")
@patch("app.mcp.client.metrics")
@patch("app.mcp.client.logger")
@patch("app.mcp.client.retry_policy")
@patch("app.mcp.client.health_check")
def test_connect_stores_tools(mock1, mock2, ...):
    mock7.return_value = {"transport": "sse"}
    client.connect()
    mock4.assert_called_once()  # tools were "fetched"
```

**Why it's dangerous**: 13 mocks means zero real code runs. The test validates that `connect()` calls things in order — but any refactor (rename, reorder, inline) breaks the test without any bug existing. Simultaneously, real bugs (token refresh failing, transport mismatch) are invisible.

**Heuristic**: If patch count > 3 for a unit test, reconsider what you're testing. For integration tests, aim for 1-2 patches (LLM + external API).

**Fix**: Mock only the external boundary.

```python
def test_connect_stores_tools():
    with patch("httpx.AsyncClient.get") as mock_http:
        mock_http.return_value = httpx.Response(200, json={"tools": [...]})
        client = MCPClient(config)
        await client.connect()
        assert len(client.tools) == 3
        assert client.status == "connected"
```

---

## 4. Echo Graph Testing

**Pattern**: Integration test builds a toy 2-node graph that just echoes input instead of using the real multi-node agent.

```python
# ANTI-PATTERN
# "Tests a simplified graph mimicking the comms agent pattern"
graph = StateGraph(MessagesState)
graph.add_node("echo", lambda s: {
    "messages": [AIMessage(content="Echo: " + s["messages"][-1].content)]
})
```

**Why it's dangerous**: The real agent has 20+ nodes, middleware, tool selection, memory, system prompt injection, follow-up actions. Testing an echo node proves StateGraph works with 2 nodes.

**Fix**: Import the real graph builder and mock only the LLM.

---

## 5. Assertion-Free Tests

**Pattern**: Test runs code but never asserts on the outcome. Passes as long as no exception is thrown.

```python
# ANTI-PATTERN
def test_process_webhook():
    data = {"event": "push", "repo": "myrepo"}
    process_webhook(data)  # no assertion — test passes if no crash
```

**Why it's dangerous**: `process_webhook` could return garbage, corrupt data, or silently skip processing. Test would pass.

**Fix**: Always assert on the meaningful output.

```python
def test_process_webhook():
    data = {"event": "push", "repo": "myrepo"}
    result = process_webhook(data)
    assert result.processed is True
    assert result.repo == "myrepo"
```

---

## 6. Mock-Assertion Tests

**Pattern**: Test's only assertions are `mock.assert_called_once_with(...)` — proving your code called a function, not that the function's result was handled correctly.

```python
# ANTI-PATTERN
def test_save_user():
    with patch("app.db.users.insert_one") as mock_db:
        save_user({"name": "Alice"})
        mock_db.assert_called_once_with({"name": "Alice"})
```

**Why it's dangerous**: If `save_user` calls `insert_one` but ignores the return value, swallows errors, or corrupts the document before insertion, this test still passes.

**Fix**: Assert on the actual effect or return value.

```python
def test_save_user():
    with patch("app.db.users.insert_one") as mock_db:
        mock_db.return_value = InsertOneResult(inserted_id="abc123")
        result = save_user({"name": "Alice"})
        assert result.id == "abc123"
        assert result.created_at is not None
```

---

## 7. Hardcoded Response Tests

**Pattern**: Test feeds a hardcoded LLM/API response and only checks that the hardcoded value propagates through.

```python
# ANTI-PATTERN
mock_llm.return_value = AIMessage(content="The answer is 42")
result = agent.invoke({"messages": [HumanMessage(content="question")]})
assert result["messages"][-1].content == "The answer is 42"
# This tests that LangGraph passes messages through. Not your logic.
```

**Fix**: Test that your code transforms, routes, or acts on the response.

```python
mock_llm.return_value = AIMessage(
    content="", tool_calls=[{"name": "create_event", "args": {"title": "Meeting"}}]
)
result = agent.invoke({"messages": [HumanMessage(content="schedule meeting")]})
# Assert YOUR routing logic directed to the right tool
assert result["tool_calls"][0]["name"] == "create_event"
# Assert YOUR tool actually processed it
assert result["events_created"] == 1
```

---

## 8. Missing Error Path Coverage

**Pattern**: Tests only cover the happy path. Production code has 5 branches; tests cover 1.

```python
# Production code
def process_payment(amount, card):
    if amount <= 0:
        raise ValueError("Invalid amount")
    if not card.is_valid():
        return PaymentResult(status="declined", reason="invalid_card")
    try:
        charge = stripe.charge(amount, card)
    except stripe.RateLimitError:
        return PaymentResult(status="retry")
    except stripe.CardError as e:
        return PaymentResult(status="declined", reason=str(e))
    return PaymentResult(status="success", charge_id=charge.id)

# ANTI-PATTERN — only tests happy path
def test_process_payment():
    result = process_payment(100, valid_card)
    assert result.status == "success"
```

**Fix**: Test each branch.

```python
def test_rejects_negative_amount(): ...
def test_declines_invalid_card(): ...
def test_retries_on_rate_limit(): ...
def test_declines_on_card_error(): ...
def test_succeeds_with_valid_payment(): ...
```

---

## 9. Shared State Leaks

**Pattern**: Tests share mutable state (module-level variables, singletons, class attributes) causing order-dependent pass/fail.

```python
# ANTI-PATTERN
_cache = {}  # module-level, shared across tests

def test_first_lookup():
    _cache["key"] = "value"
    assert lookup("key") == "value"

def test_empty_cache():
    assert lookup("key") is None  # FAILS — cache still has "key" from previous test
```

**Fix**: Use fixtures with proper scope and teardown.

```python
@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()
```

---

## 10. Test Category Misuse

**Pattern**: Tests are placed in the wrong directory, misrepresenting their coverage.

| Label | What It Actually Is | Problem |
|-------|-------------------|---------|
| `tests/e2e/` with fake tools | Unit test of framework | Falsely claims end-to-end coverage |
| `tests/integration/` with 13 mocks | Unit test of mock setup | Falsely claims integration coverage |
| `tests/unit/` testing DB queries | Integration test | Breaks without DB, unclear dependencies |

**Fix**: Enforce category rules.

- **Unit**: Zero I/O. No DB, no network, no filesystem. Mocks at the boundary.
- **Integration**: Real code, mocked external services. Uses real DB clients with test instances or in-memory alternatives.
- **E2E**: Real pipeline. Mocks only the LLM and external SaaS APIs. Tests the full request path.
