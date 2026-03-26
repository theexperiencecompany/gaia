# Pytest Patterns for Accurate Tests

## Table of Contents

1. [Fixture Design](#fixture-design)
2. [Conftest Hierarchy](#conftest-hierarchy)
3. [Parametrize for Branch Coverage](#parametrize-for-branch-coverage)
4. [Mocking External Services](#mocking-external-services)
5. [Async Testing](#async-testing)
6. [Factory Pattern](#factory-pattern)
7. [Testing Exceptions](#testing-exceptions)

---

## Fixture Design

### Scope Fixtures Correctly

```python
# Session-scoped: expensive setup shared across all tests (DB connection, app instance)
@pytest.fixture(scope="session")
def app():
    return create_app(testing=True)

# Function-scoped (default): fresh per test, prevents state leaks
@pytest.fixture
def db_session(app):
    session = app.db.create_session()
    yield session
    session.rollback()
    session.close()
```

### Return Real Objects, Not Mocks

```python
# WRONG — fixture returns a mock
@pytest.fixture
def user():
    return MagicMock(id=1, name="Alice", email="a@b.com")

# RIGHT — fixture returns a real domain object
@pytest.fixture
def user():
    return User(id=1, name="Alice", email="a@b.com")
```

### Teardown With yield

```python
@pytest.fixture
def temp_file():
    path = Path("/tmp/test_output.json")
    yield path
    path.unlink(missing_ok=True)
```

---

## Conftest Hierarchy

Place fixtures at the right level to avoid import pollution.

```
tests/
├── conftest.py              # App-wide: test client, DB connection, env vars
├── unit/
│   ├── conftest.py          # Unit-specific: mock factories, fake data builders
│   └── services/
│       ├── conftest.py      # Service-specific: mock DB clients
│       └── test_chat.py
├── integration/
│   ├── conftest.py          # Integration-specific: test DB, real app instance
│   └── api/
│       └── test_endpoints.py
└── e2e/
    ├── conftest.py          # E2E-specific: compiled agent, mock LLM
    └── test_flows.py
```

Rules:
- **Root conftest**: Environment variables, app factory, shared utilities
- **Category conftest**: Category-specific fixtures (mock factories for unit, real DB for integration)
- **Subdirectory conftest**: Domain-specific fixtures (Composio auth mocks, API client helpers)

---

## Parametrize for Branch Coverage

Use `@pytest.mark.parametrize` to test multiple branches without duplicating test bodies.

```python
@pytest.mark.parametrize("amount,card_valid,expected_status", [
    (100, True, "success"),
    (-1, True, "error"),
    (100, False, "declined"),
    (0, True, "error"),
])
def test_process_payment(amount, card_valid, expected_status):
    card = Card(valid=card_valid)
    result = process_payment(amount, card)
    assert result.status == expected_status
```

### Parametrize IDs for Readable Output

```python
@pytest.mark.parametrize("input,expected", [
    pytest.param("hello", "HELLO", id="lowercase-to-upper"),
    pytest.param("HELLO", "HELLO", id="already-upper"),
    pytest.param("", "", id="empty-string"),
])
def test_to_upper(input, expected):
    assert to_upper(input) == expected
```

---

## Mocking External Services

### Use `respx` for HTTP Mocking (Preferred Over `patch`)

```python
import respx
from httpx import Response

@respx.mock
async def test_fetch_user_from_api():
    respx.get("https://api.example.com/users/1").mock(
        return_value=Response(200, json={"id": 1, "name": "Alice"})
    )
    user = await fetch_user(user_id=1)
    assert user.name == "Alice"

@respx.mock
async def test_handles_api_error():
    respx.get("https://api.example.com/users/1").mock(
        return_value=Response(500, json={"error": "internal"})
    )
    with pytest.raises(APIError, match="internal"):
        await fetch_user(user_id=1)
```

### Patch at the Right Import Path

```python
# If chat_service.py does: from app.db.mongo import get_collection
# Patch where it's USED, not where it's DEFINED:
with patch("app.services.chat_service.get_collection") as mock:
    ...

# NOT:
with patch("app.db.mongo.get_collection") as mock:  # won't affect chat_service
    ...
```

---

## Async Testing

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await process_message("hello")
    assert result.response == "world"

# For testing streaming
@pytest.mark.asyncio
async def test_streaming():
    chunks = []
    async for chunk in stream_response("hello"):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert "".join(chunks) == "complete response"
```

---

## Factory Pattern

Use factories for complex test data instead of giant fixture trees.

```python
# tests/factories.py
def make_user(**overrides) -> User:
    defaults = {"id": 1, "name": "Alice", "email": "a@b.com", "is_premium": False}
    return User(**(defaults | overrides))

def make_conversation(**overrides) -> Conversation:
    defaults = {"id": "conv_1", "user_id": 1, "messages": [], "created_at": datetime.now()}
    return Conversation(**(defaults | overrides))

# In tests
def test_premium_user():
    user = make_user(is_premium=True)
    assert get_feature_flags(user).extended_tools is True

def test_free_user():
    user = make_user(is_premium=False)
    assert get_feature_flags(user).extended_tools is False
```

---

## Testing Exceptions

```python
# Test that the right exception is raised with the right message
def test_invalid_input_raises():
    with pytest.raises(ValueError, match="amount must be positive"):
        process_payment(amount=-1, card=valid_card)

# Test exception attributes
def test_api_error_includes_status():
    with pytest.raises(APIError) as exc_info:
        call_external_api(bad_params)
    assert exc_info.value.status_code == 422
    assert "validation" in exc_info.value.detail
```
