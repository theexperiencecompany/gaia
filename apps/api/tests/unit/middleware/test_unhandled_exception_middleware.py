"""The crash catch-all that runs inside CORS.

Starlette answers an uncaught exception in ServerErrorMiddleware, which wraps
the whole app including CORSMiddleware — so that 500 envelope carries no
Access-Control-Allow-Origin and no browser can read it. This middleware sits
innermost and converts the crash there instead.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from app.api.v1.middleware.unhandled_exception import UnhandledExceptionMiddleware

pytestmark = pytest.mark.unit


async def _boom_app(scope: Scope, receive: Receive, send: Send) -> None:
    raise RuntimeError("db down")


async def _ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("fine")(scope, receive, send)


async def _crash_midstream_app(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    raise RuntimeError("died after the status line")


def _client(app: Any) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=UnhandledExceptionMiddleware(app), raise_app_exceptions=False),
        base_url="http://test",
    )


async def test_a_crash_becomes_the_500_envelope() -> None:
    async with _client(_boom_app) as client:
        response = await client.get("/x")

    assert response.status_code == 500
    assert response.json() == {"message": "Internal server error", "code": "internal_server_error"}


async def test_a_successful_response_passes_through_untouched() -> None:
    async with _client(_ok_app) as client:
        response = await client.get("/x")

    assert response.status_code == 200
    assert response.text == "fine"


async def test_a_crash_after_the_status_line_propagates_instead_of_double_sending() -> None:
    """There is no envelope to send once the status is on the wire."""
    transport = ASGITransport(
        app=UnhandledExceptionMiddleware(_crash_midstream_app), raise_app_exceptions=True
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="died after the status line"):
            await client.get("/x")


async def test_a_websocket_scope_is_handed_on_untouched() -> None:
    """A socket needs its own receive and send; wrapping either breaks every frame."""
    seen: list[tuple[Any, Any, Any]] = []
    receive, send = MagicMock(), MagicMock()

    async def _ws_app(scope: Scope, ws_receive: Receive, ws_send: Send) -> None:
        seen.append((scope["type"], ws_receive, ws_send))

    await UnhandledExceptionMiddleware(_ws_app)({"type": "websocket"}, receive, send)

    assert seen == [("websocket", receive, send)]


async def test_the_request_body_still_reaches_the_app() -> None:
    """The app reads the body off receive; without it every POST hangs or arrives empty."""
    received: list[bytes] = []

    async def _echo_app(scope: Scope, receive: Receive, send: Send) -> None:
        received.append(await Request(scope, receive).body())
        await PlainTextResponse("read")(scope, receive, send)

    async with _client(_echo_app) as client:
        response = await client.post("/x", content=b"payload")

    assert response.status_code == 200
    assert received == [b"payload"]


async def test_a_scope_without_a_path_still_records_the_crash() -> None:
    """A raw ASGI scope need not carry path; reading it must not raise here."""
    sent: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request"}

    with patch("app.api.v1.middleware.unhandled_exception.log") as mock_log:
        await UnhandledExceptionMiddleware(_boom_app)({"type": "http"}, _receive, _send)

    assert mock_log.error.call_args.kwargs["path"] == ""
    assert sent[0]["status"] == 500


async def test_the_crash_is_recorded_on_the_wide_event() -> None:
    """LoggingMiddleware never sees a crash this converts, so it is recorded here."""
    with patch("app.api.v1.middleware.unhandled_exception.log") as mock_log:
        async with _client(_boom_app) as client:
            await client.get("/boom-path")

    mock_log.error.assert_called_once_with(
        "unhandled_exception",
        error_type="RuntimeError",
        error="db down",
        path="/boom-path",
    )


async def test_the_crash_is_attributed_in_posthog(
    posthog_provider: Callable[..., None],
) -> None:
    posthog_client = MagicMock()
    posthog_provider(available=True, client=posthog_client)

    async with _client(_boom_app) as client:
        await client.get("/x")

    posthog_client.capture_exception.assert_called_once()
    assert isinstance(posthog_client.capture_exception.call_args.args[0], RuntimeError)
