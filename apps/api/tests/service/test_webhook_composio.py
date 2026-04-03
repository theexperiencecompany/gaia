"""
Service tests: webhook idempotency and routing for Composio webhooks.

Uses real Redis for deduplication testing. Mocks signature verification
and the handler to focus on the webhook routing logic.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_composio_payload(event_type: str = "GMAIL_NEW_GMAIL_MESSAGE") -> dict:
    return {
        "data": {
            "connection_id": "conn-123",
            "connection_nano_id": "nano-123",
            "trigger_nano_id": "trig-123",
            "trigger_id": "trigger-001",
            "user_id": "test-user",
        },
        "timestamp": "2025-01-01T00:00:00Z",
        "type": event_type,
    }


def _sign_composio(
    webhook_id: str,
    timestamp: str,
    body: bytes,
    secret: str,
) -> str:
    """Return a valid Composio v1 signature header value."""
    signed_content = f"{webhook_id}.{timestamp}.{body.decode()}"
    digest = hmac.new(
        secret.encode(),
        signed_content.encode(),
        hashlib.sha256,
    ).digest()
    return f"v1,{base64.b64encode(digest).decode()}"


def _make_composio_client() -> AsyncClient:
    """Create a test AsyncClient pointed at the FastAPI app with a no-op lifespan."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

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
class TestComposioWebhookIdempotency:
    """Webhook deduplication tests that exercise the real Redis path."""

    async def test_deduplication_key_set_on_first_call(self, real_redis):
        """First call with a new webhook-id must set the deduplication key."""
        from app.db.redis import redis_cache

        webhook_id = "dedup-first-001"
        key = f"webhook:composio:{webhook_id}"

        await real_redis.delete(key)

        result = await redis_cache.client.set(key, "1", nx=True, ex=3600)
        assert result is True, "First nx=True set must succeed"

    async def test_deduplication_key_blocked_on_second_call(self, real_redis):
        """Second call with the same webhook-id must be rejected by Redis nx=True."""
        from app.db.redis import redis_cache

        webhook_id = "dedup-second-001"
        key = f"webhook:composio:{webhook_id}"

        await real_redis.delete(key)

        first = await redis_cache.client.set(key, "1", nx=True, ex=3600)
        assert first is True

        second = await redis_cache.client.set(key, "1", nx=True, ex=3600)
        assert second is None, "Duplicate key must be blocked (nx=True returns None)"

    async def test_deduplication_key_expires_after_ttl(self, real_redis):
        """Deduplication key must be stored with a TTL."""
        webhook_id = "dedup-ttl-001"
        key = f"webhook:composio:{webhook_id}"

        await real_redis.delete(key)
        await real_redis.set(key, "1", nx=True, ex=3600)

        ttl = await real_redis.ttl(key)
        assert ttl > 0, "Deduplication key must have a positive TTL"
        assert ttl <= 3600, "TTL must not exceed 3600 seconds"

    async def test_deduplication_endpoint_returns_success_on_duplicate(
        self, real_redis
    ):
        """POST with a repeated webhook-id must return 200 with duplicate message."""
        webhook_id = "dedup-endpoint-001"
        key = f"webhook:composio:{webhook_id}"
        await real_redis.delete(key)
        await real_redis.set(key, "1", nx=True, ex=3600)  # pre-seed as already seen

        payload = _make_composio_payload()
        body = json.dumps(payload).encode()
        timestamp = "2025-01-01T00:00:00Z"
        signature = _sign_composio(webhook_id, timestamp, body, "test-secret")

        async with _make_composio_client() as client:
            with patch(
                "app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"
            ):
                response = await client.post(
                    "/api/v1/webhook/composio",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "webhook-id": webhook_id,
                        "webhook-timestamp": timestamp,
                        "webhook-signature": signature,
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "Duplicate" in data.get("message", "")


@pytest.mark.service
class TestComposioWebhookRouting:
    """Signature validation and event routing tests."""

    async def test_missing_signature_returns_401(self, real_redis):
        """Request with no webhook-signature header must be rejected."""
        payload = _make_composio_payload()

        async with _make_composio_client() as client:
            with patch(
                "app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"
            ):
                response = await client.post(
                    "/api/v1/webhook/composio",
                    json=payload,
                    headers={"webhook-id": "wh-no-sig"},
                )

        assert response.status_code == 401

    async def test_invalid_signature_returns_401(self, real_redis):
        """Request with a wrong HMAC must be rejected before processing."""
        payload = _make_composio_payload()
        body = json.dumps(payload).encode()

        async with _make_composio_client() as client:
            with patch(
                "app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"
            ):
                response = await client.post(
                    "/api/v1/webhook/composio",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "webhook-id": "wh-bad-sig",
                        "webhook-timestamp": "2025-01-01T00:00:00Z",
                        "webhook-signature": "v1,badsignature==",
                    },
                )

        assert response.status_code == 401

    async def test_unhandled_event_type_returns_success(self, real_redis):
        """Unknown event type must still return 200 — webhook received but not routed."""
        webhook_id = "unhandled-event-001"
        payload = _make_composio_payload(event_type="TOTALLY_UNKNOWN_EVENT_XYZ")
        body = json.dumps(payload).encode()
        timestamp = "2025-01-01T00:00:00Z"
        signature = _sign_composio(webhook_id, timestamp, body, "test-secret")

        await real_redis.delete(f"webhook:composio:{webhook_id}")

        async with _make_composio_client() as client:
            with (
                patch(
                    "app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET",
                    "test-secret",
                ),
                patch(
                    "app.api.v1.endpoints.webhook_composio.get_handler_by_event",
                    return_value=None,
                ),
            ):
                response = await client.post(
                    "/api/v1/webhook/composio",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "webhook-id": webhook_id,
                        "webhook-timestamp": timestamp,
                        "webhook-signature": signature,
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    async def test_valid_signature_with_handler_returns_handler_result(
        self, real_redis
    ):
        """Valid signature with a matching handler must return the handler's result."""
        webhook_id = "handled-event-001"
        payload = _make_composio_payload(event_type="GMAIL_NEW_GMAIL_MESSAGE")
        body = json.dumps(payload).encode()
        timestamp = "2025-01-01T00:00:00Z"
        signature = _sign_composio(webhook_id, timestamp, body, "test-secret")

        await real_redis.delete(f"webhook:composio:{webhook_id}")

        mock_handler = MagicMock()
        mock_handler.process_event = AsyncMock(
            return_value={"status": "success", "message": "processed"}
        )

        async with _make_composio_client() as client:
            with (
                patch(
                    "app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET",
                    "test-secret",
                ),
                patch(
                    "app.api.v1.endpoints.webhook_composio.get_handler_by_event",
                    return_value=mock_handler,
                ),
            ):
                response = await client.post(
                    "/api/v1/webhook/composio",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "webhook-id": webhook_id,
                        "webhook-timestamp": timestamp,
                        "webhook-signature": signature,
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_handler.process_event.assert_called_once()
