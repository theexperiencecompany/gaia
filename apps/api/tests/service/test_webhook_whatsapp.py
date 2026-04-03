"""
Service tests: WhatsApp webhook signature validation and proxy behavior.

Uses real HMAC computation to verify the signature logic end-to-end.
Mocks the aiohttp bot proxy call to avoid network dependencies.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient


def _sign_body(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest matching Kapso's signing scheme."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_whatsapp_client() -> AsyncClient:
    """Create a test AsyncClient against the FastAPI app with a no-op lifespan."""

    @asynccontextmanager
    async def _noop_lifespan(app: FastAPI):
        yield

    def _test_middleware(app: FastAPI) -> None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _test_middleware),
    ):
        from app.config.settings import get_settings

        get_settings.cache_clear()

        from app.core.app_factory import create_app

        app = create_app()

    from app.api.v1.middleware.rate_limiter import limiter

    limiter.enabled = False

    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    )  # NOSONAR


@pytest.mark.service
class TestWhatsAppWebhookSignature:
    """Signature validation tests — no real network calls."""

    async def test_missing_signature_header_returns_401(self):
        """Request with no x-webhook-signature must be rejected."""
        body = json.dumps({"event": "message"}).encode()

        async with _make_whatsapp_client() as client:
            with patch(
                "app.config.settings.settings.KAPSO_WEBHOOK_SECRET",
                "test-secret",
            ):
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={"content-type": "application/json"},
                )

        assert response.status_code == 401

    async def test_invalid_signature_returns_401(self):
        """Request with a wrong HMAC value must be rejected."""
        body = json.dumps({"event": "message"}).encode()

        async with _make_whatsapp_client() as client:
            with patch(
                "app.config.settings.settings.KAPSO_WEBHOOK_SECRET",
                "test-secret",
            ):
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-webhook-signature": "deadbeef1234",
                    },
                )

        assert response.status_code == 401

    async def test_valid_signature_proceeds_to_proxy(self):
        """Request with a correct HMAC must pass validation and attempt bot proxy."""
        body = json.dumps({"event": "message", "data": "hello"}).encode()
        secret = "test-secret"
        signature = _sign_body(body, secret)

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        async with _make_whatsapp_client() as client:
            with (
                patch("app.config.settings.settings.KAPSO_WEBHOOK_SECRET", secret),
                patch(
                    "app.api.v1.endpoints.webhook_whatsapp.aiohttp.ClientSession",
                    return_value=mock_session,
                ),
            ):
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-webhook-signature": signature,
                    },
                )

        assert response.status_code == 200
        assert response.json()["status"] == "success"

    async def test_valid_signature_empty_body(self):
        """Empty body with correct HMAC must still pass validation."""
        body = b""
        secret = "test-secret"
        signature = _sign_body(body, secret)

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        async with _make_whatsapp_client() as client:
            with (
                patch("app.config.settings.settings.KAPSO_WEBHOOK_SECRET", secret),
                patch(
                    "app.api.v1.endpoints.webhook_whatsapp.aiohttp.ClientSession",
                    return_value=mock_session,
                ),
            ):
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-webhook-signature": signature,
                    },
                )

        assert response.status_code == 200


@pytest.mark.service
class TestWhatsAppWebhookProxy:
    """Bot proxy error-handling tests."""

    async def test_bot_returns_5xx_proxies_502(self):
        """When the bot container returns 5xx, the webhook endpoint must return 502."""
        body = json.dumps({"event": "message"}).encode()
        secret = "test-secret"
        signature = _sign_body(body, secret)

        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        async with _make_whatsapp_client() as client:
            with (
                patch("app.config.settings.settings.KAPSO_WEBHOOK_SECRET", secret),
                patch(
                    "app.api.v1.endpoints.webhook_whatsapp.aiohttp.ClientSession",
                    return_value=mock_session,
                ),
            ):
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-webhook-signature": signature,
                    },
                )

        assert response.status_code == 502
        assert response.json()["status"] == "error"

    async def test_bot_unreachable_returns_502(self):
        """When the bot container is unreachable, the endpoint must return 502."""
        import aiohttp as _aiohttp

        body = json.dumps({"event": "message"}).encode()
        secret = "test-secret"
        signature = _sign_body(body, secret)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            side_effect=_aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("connection refused")
            )
        )

        async with _make_whatsapp_client() as client:
            with (
                patch("app.config.settings.settings.KAPSO_WEBHOOK_SECRET", secret),
                patch(
                    "app.api.v1.endpoints.webhook_whatsapp.aiohttp.ClientSession",
                    return_value=mock_session,
                ),
            ):
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-webhook-signature": signature,
                    },
                )

        assert response.status_code == 502
        assert response.json()["status"] == "error"

    async def test_unconfigured_secret_returns_503(self):
        """When KAPSO_WEBHOOK_SECRET is not set, the endpoint must return 503."""
        async with _make_whatsapp_client() as client:
            with patch(
                "app.config.settings.settings.KAPSO_WEBHOOK_SECRET",
                None,
            ):
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    json={"event": "message"},
                )

        assert response.status_code == 503

    async def test_forwarded_headers_passed_to_bot(self):
        """Kapso-specific headers must be forwarded to the internal bot."""
        body = json.dumps({"event": "message"}).encode()
        secret = "test-secret"
        signature = _sign_body(body, secret)

        captured_headers: dict = {}

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        def _capture_post(url, *, data, headers):
            captured_headers.update(headers)
            mock_post_ctx = MagicMock()
            mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_ctx.__aexit__ = AsyncMock(return_value=False)
            return mock_post_ctx

        mock_session.post = MagicMock(side_effect=_capture_post)

        async with _make_whatsapp_client() as client:
            with (
                patch("app.config.settings.settings.KAPSO_WEBHOOK_SECRET", secret),
                patch(
                    "app.api.v1.endpoints.webhook_whatsapp.aiohttp.ClientSession",
                    return_value=mock_session,
                ),
            ):
                await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-webhook-event": "message.received",
                        "x-webhook-signature": signature,
                    },
                )

        assert "content-type" in captured_headers
        assert "x-webhook-event" in captured_headers
        assert "x-webhook-signature" in captured_headers
