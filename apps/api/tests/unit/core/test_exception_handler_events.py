"""What each exception handler puts on the request's wide event.

The response body has its own tests; this is the other half of the contract.
Every field here is queried in Loki when someone asks why a request failed —
status_code, path and method are what makes one findable at all, and the
500-vs-4xx split is what the ERROR-level searches rely on.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
import pytest
from sentry_sdk.types import Event
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.types import Message

from app.core import exception_handlers
from app.core.exception_handlers import (
    app_error_handler,
    http_exception_handler,
    register_exception_handlers,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.utils.errors import AppError, create_error

pytestmark = pytest.mark.unit

HANDLERS_LOG = "app.core.exception_handlers.wide_log"


def _request(method: str = "POST", path: str = "/api/v1/todos") -> Request:
    return Request(
        {"type": "http", "method": method, "path": path, "headers": [], "query_string": b""}
    )


async def test_a_client_app_error_is_a_warning_naming_the_failure() -> None:
    exc = create_error(
        message="Payment failed",
        why="Card declined",
        status_code=402,
        code="card_declined",
        public={"retry_allowed": True},
        provider="stripe",
    )

    with patch(HANDLERS_LOG) as mock_log:
        response = await app_error_handler(_request(), exc)

    assert response.status_code == 402
    mock_log.error.assert_not_called()
    mock_log.warning.assert_called_once_with(
        "app_error",
        error={
            "message": "Payment failed",
            "why": "Card declined",
            "code": "card_declined",
            "retry_allowed": True,
            "provider": "stripe",
        },
        status_code=402,
        path="/api/v1/todos",
        method="POST",
    )


async def test_a_500_app_error_is_an_error_carrying_its_exception() -> None:
    exc = create_error(message="Store down", status_code=500, code="store_down")

    with patch(HANDLERS_LOG) as mock_log:
        response = await app_error_handler(_request(), exc)

    assert response.status_code == 500
    mock_log.warning.assert_not_called()
    mock_log.error.assert_called_once_with(
        "app_error",
        exc_info=exc,
        error={"message": "Store down", "code": "store_down"},
        status_code=500,
        path="/api/v1/todos",
        method="POST",
    )


async def test_a_client_disconnect_is_a_warning_naming_the_request() -> None:
    with patch(HANDLERS_LOG) as mock_log:
        response = await exception_handlers.client_disconnect_handler(
            _request(method="PUT", path="/api/v1/webhook"), ClientDisconnect()
        )

    assert response.status_code == 499
    mock_log.warning.assert_called_once_with(
        "client_disconnected",
        error_type="ClientDisconnect",
        path="/api/v1/webhook",
        method="PUT",
    )


async def test_an_error_that_names_no_code_ships_none() -> None:
    """Clients narrow on code; inventing one routes them down a branch never chosen."""
    with patch(HANDLERS_LOG):
        response = await app_error_handler(
            _request(), create_error(message="Nope", status_code=400)
        )

    assert json.loads(response.body) == {"message": "Nope"}


async def test_validation_failures_are_counted_and_listed() -> None:
    exc = RequestValidationError(
        [{"loc": ("body", "count"), "msg": "must be an int", "type": "int_parsing"}]
    )

    with patch(HANDLERS_LOG) as mock_log:
        response = await validation_error_handler(_request(), exc)

    assert response.status_code == 422
    mock_log.warning.assert_called_once_with(
        "validation_failed",
        validation_errors=[
            {"loc": ["body", "count"], "msg": "must be an int", "type": "int_parsing"}
        ],
        error_count=1,
    )
    assert json.loads(response.body) == {
        "message": "Request validation failed",
        "code": "validation_error",
        "errors": [{"loc": ["body", "count"], "msg": "must be an int", "type": "int_parsing"}],
    }


async def test_a_challenge_header_survives_the_envelope() -> None:
    """A 401 without WWW-Authenticate is a different contract, not a shorter one."""
    exc = StarletteHTTPException(
        status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )

    with patch(HANDLERS_LOG):
        response = await http_exception_handler(_request(method="GET"), exc)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert json.loads(response.body) == {"message": "Not authenticated"}


async def test_a_4xx_http_exception_is_a_warning_with_its_detail() -> None:
    with patch(HANDLERS_LOG) as mock_log:
        await http_exception_handler(
            _request(method="GET"), StarletteHTTPException(status_code=404, detail="Todo not found")
        )

    mock_log.error.assert_not_called()
    mock_log.warning.assert_called_once_with(
        "http_exception",
        status_code=404,
        detail="Todo not found",
        path="/api/v1/todos",
        method="GET",
    )


async def test_a_5xx_http_exception_is_an_error_so_level_searches_find_it() -> None:
    with patch(HANDLERS_LOG) as mock_log:
        await http_exception_handler(
            _request(), StarletteHTTPException(status_code=500, detail="boom")
        )

    mock_log.warning.assert_not_called()
    assert mock_log.error.call_args.args[0] == "http_exception"
    assert mock_log.error.call_args.kwargs["status_code"] == 500


async def test_an_explicit_cause_is_named_on_the_event() -> None:
    """Only an explicit raise-from names the real failure on the event."""
    exc = StarletteHTTPException(status_code=502, detail="upstream")
    exc.__cause__ = ValueError("connection reset")

    with patch(HANDLERS_LOG) as mock_log:
        await http_exception_handler(_request(), exc)

    kwargs: dict[str, Any] = mock_log.error.call_args.kwargs
    assert kwargs["error_type"] == "ValueError"
    assert kwargs["error"] == "connection reset"


async def test_an_incidental_context_is_not_reported_as_the_cause() -> None:
    """__context__ is set by any raise inside an except block; naming it misleads."""
    exc = StarletteHTTPException(status_code=502, detail="upstream")
    exc.__context__ = ValueError("unrelated")

    with patch(HANDLERS_LOG) as mock_log:
        await http_exception_handler(_request(), exc)

    assert "error_type" not in mock_log.error.call_args.kwargs
    assert "error" not in mock_log.error.call_args.kwargs


async def test_a_bodiless_status_keeps_its_headers_and_is_still_recorded() -> None:
    exc = StarletteHTTPException(status_code=304, headers={"ETag": '"v1"'})

    with patch(HANDLERS_LOG) as mock_log:
        response = await http_exception_handler(_request(method="GET"), exc)

    assert response.status_code == 304
    assert response.headers["etag"] == '"v1"'
    assert response.body == b""
    mock_log.warning.assert_called_once()


async def test_the_registration_covers_every_kind_of_failure() -> None:
    """An unregistered handler silently reverts that path to Starlette's own body."""
    app = MagicMock()
    register_exception_handlers(app)

    registered = [call.args[0] for call in app.exception_handler.call_args_list]
    assert registered == [
        AppError,
        RequestValidationError,
        StarletteHTTPException,
        ClientDisconnect,
        Exception,
    ]
    # The decorator form returns the handler it was given, so each registration
    # must hand the real function over, not a placeholder.
    handlers = [call.args[0] for call in app.exception_handler.return_value.call_args_list]
    assert handlers == [
        app_error_handler,
        validation_error_handler,
        http_exception_handler,
        exception_handlers.client_disconnect_handler,
        unhandled_exception_handler,
    ]


def _app_raising(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


async def _get(app: FastAPI, path: str) -> int:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.get(path)).status_code


@pytest.mark.regression
async def test_a_client_error_app_error_is_not_a_sentry_error(sentry_events: list[Event]) -> None:
    exc = create_error(message="Sandbox execute rate limit hit", status_code=429)

    status_code = await _get(_app_raising(exc), "/boom")

    assert status_code == 429
    assert sentry_events == []


@pytest.mark.regression
async def test_a_server_error_app_error_reaches_sentry_once_as_its_exception(
    sentry_events: list[Event],
) -> None:
    exc = create_error(message="Upstream store unavailable", status_code=503)

    status_code = await _get(_app_raising(exc), "/boom")

    assert status_code == 503
    assert [event["exception"]["values"][-1]["type"] for event in sentry_events] == ["AppError"]


@pytest.mark.regression
async def test_a_client_hanging_up_mid_body_is_a_quiet_499(sentry_events: list[Event]) -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/webhook")
    async def webhook(request: Request) -> None:
        await request.body()

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/webhook",
        "raw_path": b"/webhook",
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "client": ("client", 1234),
    }
    await app(scope, receive, send)

    assert sent[0]["status"] == 499
    assert sentry_events == []
