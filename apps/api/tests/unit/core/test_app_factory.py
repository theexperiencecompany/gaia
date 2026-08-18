"""Tests for app/core/app_factory.py — the /metrics bearer guard and the
StarletteHTTPException handler's recorded failure."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.config.settings import settings
from tests.conftest import _create_test_app

METRICS_TOKEN = "metrics_token_secret"


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """One app built with a metrics token configured — the guarded branch."""
    with patch.object(settings, "METRICS_TOKEN", METRICS_TOKEN):
        return _create_test_app()


@pytest.fixture(scope="module")
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_the_configured_token_opens_metrics(client: TestClient) -> None:
    """The exact configured token is what the guard compares against."""
    response = client.get("/metrics", headers={"Authorization": f"Bearer {METRICS_TOKEN}"})

    assert response.status_code == 200


def test_a_wrong_token_is_forbidden(client: TestClient) -> None:
    """A near-miss token is rejected, not waved through."""
    response = client.get("/metrics", headers={"Authorization": f"Bearer {METRICS_TOKEN}_wrong"})

    assert response.status_code == 403


def test_no_credentials_never_reach_the_comparison(client: TestClient) -> None:
    """HTTPBearer(auto_error=True) rejects an unauthenticated scrape with 401."""
    response = client.get("/metrics")

    assert response.status_code == 401


def _request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


async def _record_failure(
    app: FastAPI, exc: StarletteHTTPException, request: Request
) -> dict[str, object]:
    """Drive the registered handler and return what it wrote to the wide event."""
    handler = app.exception_handlers[StarletteHTTPException]
    captured: dict[str, object] = {}

    def _capture(event: str, **fields: object) -> None:
        captured.update(event=event, **fields)

    with patch("app.core.app_factory.wide_log") as wide_log:
        wide_log.error.side_effect = _capture
        wide_log.warning.side_effect = _capture
        await handler(request, exc)
    return captured


async def test_the_failure_carries_the_request_and_the_exception(app: FastAPI) -> None:
    """Status, detail, path and method all land on the wide event."""
    exc = StarletteHTTPException(status_code=404, detail="Todo not found")

    failure = await _record_failure(app, exc, _request("DELETE", "/api/v1/todos/1"))

    assert failure == {
        "event": "http_exception",
        "status_code": 404,
        "detail": "Todo not found",
        "path": "/api/v1/todos/1",
        "method": "DELETE",
    }


async def test_an_explicit_cause_is_named_on_the_failure(app: FastAPI) -> None:
    """`raise HTTPException(...) from e` records the real underlying error."""
    exc = StarletteHTTPException(status_code=500, detail="Failed to create todo")
    exc.__cause__ = RuntimeError("db down")

    failure = await _record_failure(app, exc, _request("POST", "/api/v1/todos"))

    assert failure["error_type"] == "RuntimeError"
    assert failure["error"] == "db down"
