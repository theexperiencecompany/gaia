"""The 504 a request gets when it outruns its budget.

Its timeout is resolved at construction rather than bound as a default
argument, so the module constant stays the live budget — the app never passes
one, and a default bound at class definition made the constant decorative.
"""

from typing import Any
from unittest.mock import patch

import anyio
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from app.api.v1.middleware import timeout as timeout_module
from app.api.v1.middleware.timeout import (
    TIMEOUT_EXCLUDE_PREFIXES,
    TIMEOUT_RETRY_AFTER_SECONDS,
    RequestTimeoutMiddleware,
)

pytestmark = pytest.mark.unit


async def _slow_app(scope: Scope, receive: Receive, send: Send) -> None:
    await anyio.sleep(5)
    await PlainTextResponse("late")(scope, receive, send)


async def _fast_app(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("quick")(scope, receive, send)


async def _stalls_after_starting(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await anyio.sleep(5)
    await send({"type": "http.response.body", "body": b"late"})


def _client(app: Any, **kwargs: Any) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=RequestTimeoutMiddleware(app, **kwargs)),
        base_url="http://test",
    )


def test_the_module_constant_is_the_live_default() -> None:
    with patch.object(timeout_module, "DEFAULT_TIMEOUT_SECONDS", 1.5):
        assert RequestTimeoutMiddleware(_fast_app).timeout == 1.5


def test_an_explicit_budget_wins_over_the_default() -> None:
    assert RequestTimeoutMiddleware(_fast_app, timeout=7.0).timeout == 7.0


async def test_an_overrunning_request_is_the_504_envelope_with_a_retry_hint() -> None:
    async with _client(_slow_app, timeout=0.01) as client:
        response = await client.get("/x")

    assert response.status_code == 504
    assert response.json()["code"] == "request_timeout"
    assert response.headers["retry-after"] == str(TIMEOUT_RETRY_AFTER_SECONDS)


async def test_a_started_response_is_not_overwritten_with_a_504() -> None:
    """Once the status line is on the wire the middleware can only warn, never answer twice."""
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": [], "query_string": b""}
    with patch.object(timeout_module, "log") as mock_log:
        await RequestTimeoutMiddleware(_stalls_after_starting, timeout=0.01)(scope, receive, send)

    assert [message["type"] for message in sent] == ["http.response.start"]
    mock_log.warning.assert_called_once()
    assert "already started" in mock_log.warning.call_args.args[0]
    assert mock_log.warning.call_args.kwargs["path"] == "/x"


async def test_a_request_inside_its_budget_is_untouched() -> None:
    async with _client(_fast_app, timeout=5.0) as client:
        response = await client.get("/x")

    assert response.status_code == 200
    assert response.text == "quick"


async def test_a_long_lived_path_is_never_cut_off() -> None:
    """SSE and websocket paths are long-lived; a timeout would close every stream."""
    excluded = TIMEOUT_EXCLUDE_PREFIXES[0]
    async with _client(_slow_app, timeout=0.01, exclude_prefixes=(excluded,)) as client:
        with anyio.move_on_after(0.2) as scope:
            await client.get(f"{excluded}/thing")

    assert scope.cancelled_caught, "an excluded path must outlive the budget, not 504"
