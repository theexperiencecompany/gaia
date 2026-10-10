"""Every non-2xx body the app emits is one ErrorEnvelope.

Before this there were two shapes on the wire — AppError rendered flat
{message, why, fix, ...} while HTTPException rendered {detail} —
and 17 client files each guessed which one they were holding. These pin the
single shape for every path that produces an error body: the two exception
kinds, request validation, the crash handler, and the middlewares that answer
before a route runs.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
import pytest

from app.core.app_factory import create_app
from app.schemas.errors import (
    ERROR_RESPONSES,
    HTML_ROUTE_ERROR_RESPONSES,
    ErrorEnvelope,
    ValidationIssue,
    error_responses,
)
from app.utils.errors import AppError, create_error


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _cors_only_middleware(app: FastAPI) -> None:
    app.add_middleware(CORSMiddleware, allow_origins=["*"])


class _Payload(BaseModel):
    count: int


@pytest.fixture
def app() -> FastAPI:
    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _cors_only_middleware),
    ):
        built = create_app()
    router = APIRouter()

    @router.get("/app-error")
    async def _app_error() -> None:
        raise create_error(
            message="Payment failed",
            why="Card declined",
            fix="Try another card",
            status_code=402,
            code="card_declined",
            public={"retry_allowed": True},
            provider="stripe",
            charge_id="ch_abc123",
        )

    @router.get("/http-string")
    async def _http_string() -> None:
        raise HTTPException(status_code=404, detail="Todo not found")

    @router.get("/http-structured")
    async def _http_structured() -> None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INTEGRATION_NOT_CONNECTED",
                "message": "Connect Gmail",
                "toolkit": "gmail",
            },
            headers={"X-Reason": "integration"},
        )

    @router.get("/http-structured-no-message")
    async def _http_structured_no_message() -> None:
        raise HTTPException(status_code=403, detail={"code": "x", "toolkit": "gmail"})

    @router.get("/http-non-str-code")
    async def _http_non_str_code() -> None:
        raise HTTPException(status_code=409, detail={"code": 409, "message": "Already linked"})

    @router.get("/app-error-public-message")
    async def _app_error_public_message() -> None:
        raise AppError(
            message="Payment failed",
            status_code=402,
            public={"message": "stale copy", "code": 402, "message_id": "m1"},
        )

    @router.get("/app-error-non-standard-status")
    async def _app_error_non_standard_status() -> None:
        raise AppError(message="Upstream said 499", status_code=499)

    @router.get("/app-error-public-datetime")
    async def _app_error_public_datetime() -> None:
        raise AppError(
            message="Try later",
            status_code=409,
            public={"retry_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)},
        )

    @router.get("/http-list-detail")
    async def _http_list_detail() -> None:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "count"], "msg": "must be an int", "type": "int_parsing"}],
        )

    @router.get("/http-non-standard-status-no-message")
    async def _http_non_standard_status_no_message() -> None:
        raise HTTPException(status_code=499, detail={"code": "client_closed"})

    @router.get("/http-list-detail-ragged")
    async def _http_list_detail_ragged() -> None:
        raise HTTPException(status_code=400, detail=[{"loc": ("body", 0)}, "plain string", 42])

    @router.get("/http-mapping-raw-errors")
    async def _http_mapping_raw_errors() -> None:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Bad",
                "errors": ["boom", {"loc": "body", "msg": "m", "type": "t"}],
            },
        )

    @router.get("/http-bad-meta-types")
    async def _http_bad_meta_types() -> None:
        raise HTTPException(
            status_code=400, detail={"message": "Bad", "why": 7, "fix": [], "errors": "nope"}
        )

    @router.post("/validate")
    async def _validate(payload: _Payload) -> _Payload:
        return payload

    @router.get("/not-modified")
    async def _not_modified() -> None:
        raise HTTPException(status_code=304, headers={"ETag": '"v1"'})

    @router.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("boom")

    built.include_router(router, responses=ERROR_RESPONSES)
    return built


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        yield c


def _envelope(body: dict[str, Any]) -> ErrorEnvelope:
    assert "detail" not in body, f"the envelope never nests under detail: {body}"
    return ErrorEnvelope.model_validate(body)


@pytest.mark.unit
class TestOneEnvelope:
    async def test_app_error_is_the_envelope(self, client: AsyncClient) -> None:
        resp = await client.get("/app-error")
        body = resp.json()
        assert resp.status_code == 402
        assert _envelope(body).message == "Payment failed"
        assert body["code"] == "card_declined"
        assert body["why"] == "Card declined"
        assert body["fix"] == "Try another card"
        assert body["retry_allowed"] is True
        assert "provider" not in body, "meta is wide-event context, never the wire"
        assert "charge_id" not in body

    async def test_http_exception_string_detail_becomes_message(self, client: AsyncClient) -> None:
        resp = await client.get("/http-string")
        assert resp.status_code == 404
        assert resp.json() == {"message": "Todo not found"}

    async def test_http_exception_structured_detail_flattens(self, client: AsyncClient) -> None:
        resp = await client.get("/http-structured")
        body = resp.json()
        assert resp.status_code == 403
        assert _envelope(body).code == "INTEGRATION_NOT_CONNECTED"
        assert body["message"] == "Connect Gmail"
        assert body["toolkit"] == "gmail"
        assert resp.headers["x-reason"] == "integration", "exc.headers must survive the rewrite"

    async def test_structured_detail_without_message_keeps_its_status(
        self, client: AsyncClient
    ) -> None:
        """A mapping detail with no message renders under the status phrase, never as a 500."""
        resp = await client.get("/http-structured-no-message")
        body = resp.json()
        assert resp.status_code == 403
        assert _envelope(body).message == "Forbidden"
        assert body["code"] == "x"
        assert body["toolkit"] == "gmail"

    async def test_a_non_string_code_is_dropped_not_a_500(self, client: AsyncClient) -> None:
        resp = await client.get("/http-non-str-code")
        assert resp.status_code == 409
        assert resp.json() == {"message": "Already linked"}

    async def test_app_error_message_wins_over_public_and_bad_code(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/app-error-public-message")
        assert resp.status_code == 402
        assert resp.json() == {"message": "Payment failed", "message_id": "m1"}

    async def test_a_non_standard_status_renders_instead_of_raising(
        self, client: AsyncClient
    ) -> None:
        """HTTPStatus(499) raises; a forwarded upstream code must still be the envelope."""
        resp = await client.get("/app-error-non-standard-status")
        assert resp.status_code == 499
        assert _envelope(resp.json()).message == "Upstream said 499"

    async def test_public_context_may_carry_a_datetime(self, client: AsyncClient) -> None:
        resp = await client.get("/app-error-public-datetime")
        assert resp.status_code == 409
        assert resp.json()["retry_at"] == "2026-01-02T03:04:05Z"

    async def test_a_list_detail_renders_as_validation_issues(self, client: AsyncClient) -> None:
        resp = await client.get("/http-list-detail")
        body = resp.json()
        assert resp.status_code == 422
        envelope = _envelope(body)
        assert envelope.message == HTTPStatus(422).phrase
        assert envelope.errors is not None
        assert envelope.errors == [
            ValidationIssue(loc=["body", "count"], msg="must be an int", type="int_parsing")
        ]

    async def test_an_unknown_status_with_no_message_has_a_generic_one(
        self, client: AsyncClient
    ) -> None:
        """HTTPStatus(499) has no phrase; raising would turn the status into a bare 500."""
        resp = await client.get("/http-non-standard-status-no-message")
        assert resp.status_code == 499
        assert resp.json() == {"message": "Error", "code": "client_closed"}

    async def test_a_ragged_list_detail_still_renders_every_entry(
        self, client: AsyncClient
    ) -> None:
        """A non-mapping entry becomes its own message, never a Python repr."""
        resp = await client.get("/http-list-detail-ragged")
        assert resp.status_code == 400
        assert _envelope(resp.json()).errors == [
            ValidationIssue(loc=["body", 0], msg="", type="value_error"),
            ValidationIssue(loc=[], msg="plain string", type="value_error"),
            ValidationIssue(loc=[], msg="42", type="value_error"),
        ]

    async def test_a_mapping_detail_with_raw_errors_is_normalized_not_a_500(
        self, client: AsyncClient
    ) -> None:
        """Raw entries are normalized first; a string loc stays one value."""
        resp = await client.get("/http-mapping-raw-errors")
        assert resp.status_code == 400
        assert _envelope(resp.json()).errors == [
            ValidationIssue(loc=[], msg="boom", type="value_error"),
            ValidationIssue(
                loc=[], msg="{'loc': 'body', 'msg': 'm', 'type': 't'}", type="value_error"
            ),
        ]

    async def test_wrongly_typed_declared_fields_are_dropped_not_a_500(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/http-bad-meta-types")
        assert resp.status_code == 400
        assert resp.json() == {"message": "Bad"}

    async def test_validation_failure_is_the_envelope(self, client: AsyncClient) -> None:
        resp = await client.post("/validate", json={"count": "many"})
        body = resp.json()
        assert resp.status_code == 422
        envelope = _envelope(body)
        assert envelope.message == "Request validation failed"
        assert envelope.code == "validation_error"
        assert envelope.errors is not None
        assert envelope.errors[0].loc == ["body", "count"]
        assert envelope.errors[0].type == "int_parsing"

    async def test_a_bodiless_status_keeps_its_headers_and_sends_no_body(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/not-modified")
        assert resp.status_code == 304
        assert resp.headers["etag"] == '"v1"'
        assert resp.content == b""

    async def test_unhandled_exception_is_the_envelope(self, client: AsyncClient) -> None:
        resp = await client.get("/boom")
        assert resp.status_code == 500
        assert _envelope(resp.json()).code == "internal_server_error"

    def test_every_route_documents_the_envelope(self, app: FastAPI) -> None:
        """The schema names ErrorEnvelope for 4xx/5xx, so the generated client types carry it."""
        schema = app.openapi()
        responses = schema["paths"]["/api/v1/todos"]["get"]["responses"]
        assert "4XX" in responses and "5XX" in responses
        for status in ("4XX", "5XX", "422"):
            ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
            assert ref == "#/components/schemas/ErrorEnvelope"
        stray = [
            f"{method.upper()} {path}"
            for path, ops in schema["paths"].items()
            for method, op in ops.items()
            if "HTTPValidationError" in str(op.get("responses", {}))
        ]
        assert stray == [], f"routes still documenting FastAPI's own 422 body: {stray}"
        assert "HTTPValidationError" not in schema["components"]["schemas"]

    def test_the_health_router_documents_the_envelope_too(self, app: FastAPI) -> None:
        responses = app.openapi()["paths"]["/health"]["get"]["responses"]
        for status in ("4XX", "5XX"):
            ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
            assert ref == "#/components/schemas/ErrorEnvelope"

    def test_the_dev_router_is_mounted_under_the_api_prefix_in_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ENV", "development")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", "dev@example.com")
        with (
            patch("app.core.app_factory.lifespan", _noop_lifespan),
            patch("app.core.app_factory.configure_middleware", _cors_only_middleware),
        ):
            schema = create_app().openapi()
        responses = schema["paths"]["/api/v1/dev/users"]["post"]["responses"]
        for status in ("4XX", "5XX"):
            ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
            assert ref == "#/components/schemas/ErrorEnvelope"


@pytest.mark.unit
class TestRouteErrorDeclarations:
    def test_error_responses_declares_the_envelope_model_with_each_description(self) -> None:
        assert error_responses({400: "Bad token", 404: "Not found"}) == {
            400: {"model": ErrorEnvelope, "description": "Bad token"},
            404: {"model": ErrorEnvelope, "description": "Not found"},
        }

    def test_error_responses_with_no_descriptions_is_empty(self) -> None:
        assert error_responses({}) == {}

    def test_html_routes_spell_out_the_json_envelope_content(self) -> None:
        json_envelope = {
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
            }
        }
        assert {
            422: json_envelope,
            "4XX": json_envelope,
            "5XX": json_envelope,
        } == HTML_ROUTE_ERROR_RESPONSES
