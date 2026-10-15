"""Who may call GET /health/ready: anyone on a self-host or dev instance, only the scraper on GAIA Cloud.

Each call pings every datastore and names them with latencies and error types,
so on the public hosted API it is both an amplifier and an information leak.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
import pytest

from app.config.deployment import DeploymentKind
from app.config.settings import settings
from app.core.app_factory import create_app
from app.models.health_models import DependencyStatus, ReadinessResponse

METRICS_TOKEN = "metrics-token-for-tests"  # pragma: allowlist secret


@asynccontextmanager
async def _noop_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _cors_only(app: FastAPI) -> None:
    app.add_middleware(CORSMiddleware, allow_origins=["*"])


async def _ready() -> ReadinessResponse:
    return ReadinessResponse(
        status="ready", dependencies=[DependencyStatus(name="mongodb", ok=True, latency_ms=1.0)]
    )


@pytest.fixture(autouse=True)
def _stub_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v1.endpoints.readiness.check_readiness", _ready)


def _as_deployment(
    monkeypatch: pytest.MonkeyPatch, kind: DeploymentKind, metrics_token: str | None
) -> AsyncClient:
    auth_mode = "local" if kind is DeploymentKind.SELFHOST else "workos"
    monkeypatch.setattr(settings, "ENV", kind)
    monkeypatch.setattr(settings, "AUTH_MODE", auth_mode)
    monkeypatch.setattr(settings, "BLOB_STORE", None)
    monkeypatch.setattr(settings, "METRICS_TOKEN", metrics_token)
    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _cors_only),
    ):
        app = create_app()
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.mark.parametrize("kind", [DeploymentKind.SELFHOST, DeploymentKind.DEVELOPMENT])
async def test_an_instance_operator_reads_readiness_without_a_token(
    monkeypatch: pytest.MonkeyPatch, kind: DeploymentKind
) -> None:
    async with _as_deployment(monkeypatch, kind, metrics_token=None) as client:
        resp = await client.get("/health/ready")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


async def test_gaia_cloud_refuses_readiness_without_the_metrics_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _as_deployment(monkeypatch, DeploymentKind.PRODUCTION, METRICS_TOKEN) as client:
        anonymous = await client.get("/health/ready")
        wrong = await client.get("/health/ready", headers={"Authorization": "Bearer not-it"})

    assert anonymous.status_code in (401, 403)
    assert wrong.status_code == 403
    assert "mongodb" not in anonymous.text


async def test_gaia_cloud_serves_readiness_to_the_metrics_scraper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _as_deployment(monkeypatch, DeploymentKind.PRODUCTION, METRICS_TOKEN) as client:
        resp = await client.get(
            "/health/ready", headers={"Authorization": f"Bearer {METRICS_TOKEN}"}
        )

    assert resp.status_code == 200


async def test_gaia_cloud_without_a_metrics_token_does_not_serve_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _as_deployment(monkeypatch, DeploymentKind.PRODUCTION, None) as client:
        resp = await client.get("/health/ready")

    assert resp.status_code == 404


DOC_PATHS = ("/openapi.json", "/docs", "/redoc")


async def test_development_serves_the_api_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _as_deployment(monkeypatch, DeploymentKind.DEVELOPMENT, None) as client:
        statuses = [(await client.get(path)).status_code for path in DOC_PATHS]

    assert statuses == [200, 200, 200]


@pytest.mark.parametrize("kind", [DeploymentKind.SELFHOST, DeploymentKind.PRODUCTION])
async def test_real_deployments_hide_the_api_docs(
    monkeypatch: pytest.MonkeyPatch, kind: DeploymentKind
) -> None:
    async with _as_deployment(monkeypatch, kind, METRICS_TOKEN) as client:
        statuses = [(await client.get(path)).status_code for path in DOC_PATHS]

    assert statuses == [404, 404, 404]


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
async def test_root_routes_document_the_error_envelope(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    async with _as_deployment(monkeypatch, DeploymentKind.DEVELOPMENT, None) as client:
        schema = (await client.get("/openapi.json")).json()

    assert {"4XX", "5XX"} <= set(schema["paths"][path]["get"]["responses"])


@pytest.mark.parametrize("kind", [DeploymentKind.SELFHOST, DeploymentKind.PRODUCTION])
async def test_the_dev_router_never_mounts_outside_development(
    monkeypatch: pytest.MonkeyPatch, kind: DeploymentKind
) -> None:
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", "dev@gaia.test")
    async with _as_deployment(monkeypatch, kind, METRICS_TOKEN) as client:
        resp = await client.get("/api/v1/dev/subagents")

    assert resp.status_code == 404
