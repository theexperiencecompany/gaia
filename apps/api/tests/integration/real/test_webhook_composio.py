"""
Service tests: webhook idempotency and routing for Composio webhooks.

Uses real Redis for deduplication testing. Mocks signature verification
and the handler to focus on the webhook routing logic.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest


def _endpoint():
    """The webhook endpoint module, imported lazily.

    Importing it at test-module scope makes it the first thing to touch
    ``app.services.triggers`` and trips a pre-existing circular import there;
    by test time the app has already imported it. Patching the module object
    beats patching by dotted string, which resolves through the package
    attribute and is not reliably present.
    """
    from app.api.v1.endpoints import webhook_composio

    return webhook_composio


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


def _make_connection_payload(
    *,
    status: str = "EXPIRED",
    auth_config_id: str = "ac_test_config",
    toolkit: str = "NOTION",
    user_id: str = "507f1f77bcf86cd799439011",
) -> dict:
    """A `composio.connected_account.expired` delivery.

    Mirrors the SDK's ``ConnectionExpiredEvent`` / raw snake_case
    ``SingleConnectedAccountDetailedResponse``. Note it carries NONE of the
    trigger identifiers ``ComposioWebhookEvent`` types as required ``str`` —
    that is exactly why the endpoint must branch before building that model.
    """
    return {
        "id": "msg_847cdfcd-d219-4f18-a6dd-91acd42ca94a",
        "type": "composio.connected_account.expired",
        "timestamp": "2026-08-10T05:44:33Z",
        "metadata": {"project_id": "proj_x", "org_id": "org_x"},
        "data": {
            "id": "ca_xxxxxxxxxxxx",
            "user_id": user_id,
            "status": status,
            "status_reason": "refresh_token_revoked",
            "is_disabled": False,
            "toolkit": {"slug": toolkit},
            "auth_config": {
                "id": auth_config_id,
                "auth_scheme": "OAUTH2",
                "is_composio_managed": True,
                "is_disabled": False,
            },
            "state": {"authScheme": "OAUTH2", "val": {"status": status}},
            "data": {},
            "params": {},
            "created_at": "2026-05-02T09:12:44Z",
            "updated_at": "2026-08-10T05:44:33Z",
        },
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

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")  # NOSONAR


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

    async def test_deduplication_endpoint_returns_success_on_duplicate(self, real_redis):
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
            with patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"):
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
            with patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"):
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
            with patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"):
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

    async def test_valid_signature_with_handler_returns_handler_result(self, real_redis):
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
        # The endpoint dispatches the handler with asyncio.create_task and acks
        # immediately, so the task has not run by the time the response returns.
        # Yield until it does rather than asserting into the race.
        for _ in range(100):
            if mock_handler.process_event.await_count:
                break
            await asyncio.sleep(0)
        # "Webhook accepted" is the handler branch; the no-handler branch acks
        # "Webhook received" with the same status, so this is what distinguishes them.
        assert data["message"] == "Webhook accepted"
        mock_handler.process_event.assert_called_once()


@pytest.mark.service
class TestComposioConnectionEvents:
    """`composio.connected_account.expired` routing.

    Before this path existed the endpoint 500'd on every connection event —
    `ComposioWebhookEvent` requires four trigger identifiers a connection event
    does not carry — so Composio retried the same delivery forever.
    """

    @pytest.fixture(autouse=True)
    def pause(self):
        """The workflow layer is mocked at its own seam — it is not this file's subject.

        Left real it would query Mongo from the background task, and a failure
        there would abort the expiry these tests assert on.
        """
        with patch.object(
            _endpoint(),
            "pause_workflows_for_expired_integration",
            new_callable=AsyncMock,
            return_value=[],
        ) as pause:
            yield pause

    async def _post(self, real_redis, payload: dict, *, webhook_id: str):
        body = json.dumps(payload).encode()
        timestamp = "2025-01-01T00:00:00Z"
        signature = _sign_composio(webhook_id, timestamp, body, "test-secret")
        await real_redis.delete(f"webhook:composio:{webhook_id}")

        async with _make_composio_client() as client:
            with patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"):
                return await client.post(
                    "/api/v1/webhook/composio",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "webhook-id": webhook_id,
                        "webhook-timestamp": timestamp,
                        "webhook-signature": signature,
                    },
                )

    async def test_an_expired_connection_is_accepted_and_runs_the_expiry_transition(
        self, real_redis
    ):
        integration = MagicMock()
        integration.id = "notion"

        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=integration),
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            response = await self._post(
                real_redis, _make_connection_payload(), webhook_id="conn-expired-001"
            )

            assert response.status_code == 200
            assert response.json()["message"] == "Connection event accepted"

            for _ in range(100):
                if expire.await_count:
                    break
                await asyncio.sleep(0)

        expire.assert_awaited_once_with(
            "507f1f77bcf86cd799439011",
            "notion",
            reason="refresh_token_revoked",
            trigger="webhook",
            notify=True,
            connected_account_id="ca_xxxxxxxxxxxx",
            paused_workflows=[],
        )

    async def test_it_pauses_the_dependent_workflows_and_hands_the_titles_to_the_expiry(
        self, real_redis, pause
    ):
        # The endpoint owns the pause because `integration_expiry` cannot import
        # the workflow layer, and the titles are what turn the reconnect
        # notification into "2 workflows are paused" instead of bare "reconnect".
        integration = MagicMock()
        integration.id = "notion"
        pause.return_value = ["Morning digest", "Invoice filing"]

        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=integration),
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            await self._post(real_redis, _make_connection_payload(), webhook_id="conn-paused-001")

            for _ in range(100):
                if expire.await_count:
                    break
                await asyncio.sleep(0)

        pause.assert_awaited_once_with("507f1f77bcf86cd799439011", "notion")
        assert expire.await_args.kwargs["paused_workflows"] == [
            "Morning digest",
            "Invoice filing",
        ]

    async def test_the_toolkit_slug_resolves_the_integration_when_the_auth_config_does_not(
        self, real_redis
    ):
        integration = MagicMock()
        integration.id = "notion"

        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=None),
            patch.object(
                _endpoint(), "get_integration_by_toolkit", return_value=integration
            ) as by_toolkit,
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            response = await self._post(
                real_redis, _make_connection_payload(), webhook_id="conn-fallback-001"
            )
            for _ in range(100):
                if expire.await_count:
                    break
                await asyncio.sleep(0)

        assert response.status_code == 200
        by_toolkit.assert_called_once_with("NOTION")
        expire.assert_awaited_once()

    async def test_an_unrecognised_integration_is_acked_and_dropped(self, real_redis):
        # A 4xx/5xx here would make Composio redeliver an event GAIA can never act on.
        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=None),
            patch.object(_endpoint(), "get_integration_by_toolkit", return_value=None),
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            response = await self._post(
                real_redis, _make_connection_payload(), webhook_id="conn-unknown-001"
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Unknown integration ignored"
        expire.assert_not_awaited()

    @pytest.mark.parametrize("status", ["EXPIRED", "REVOKED", "FAILED"])
    async def test_every_unusable_status_expires_the_integration(self, real_redis, status):
        integration = MagicMock()
        integration.id = "notion"

        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=integration),
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            response = await self._post(
                real_redis,
                _make_connection_payload(status=status),
                webhook_id=f"conn-dead-{status}",
            )
            for _ in range(100):
                if expire.await_count:
                    break
                await asyncio.sleep(0)

        assert response.status_code == 200
        expire.assert_awaited_once()

    @pytest.mark.parametrize("status", ["ACTIVE", "INITIALIZING", "INITIATED", "INACTIVE"])
    async def test_a_status_the_user_cannot_fix_causes_no_expiry(self, real_redis, status):
        # INACTIVE is a deliberate disable (PATCH .../status), not a dead grant —
        # a reconnect would not fix it, so it must not expire or pause anything.
        integration = MagicMock()
        integration.id = "notion"

        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=integration),
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            response = await self._post(
                real_redis,
                _make_connection_payload(status=status),
                webhook_id=f"conn-live-{status}",
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Connection status not terminal"
        expire.assert_not_awaited()

    async def test_an_unparseable_connection_envelope_is_acked_not_raised(self, real_redis):
        # Webhook-version drift must degrade to a logged drop, never a 500 that
        # Composio retries forever.
        payload = _make_connection_payload()
        del payload["data"]["toolkit"]

        with patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire:
            response = await self._post(real_redis, payload, webhook_id="conn-malformed-001")

        assert response.status_code == 200
        assert response.json()["message"] == "Connection event not understood"
        expire.assert_not_awaited()

    async def test_a_redelivered_connection_event_is_deduped_like_any_other(self, real_redis):
        integration = MagicMock()
        integration.id = "notion"
        webhook_id = "conn-replay-001"

        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=integration),
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            first = await self._post(real_redis, _make_connection_payload(), webhook_id=webhook_id)
            for _ in range(100):
                if expire.await_count:
                    break
                await asyncio.sleep(0)

            body = json.dumps(_make_connection_payload()).encode()
            timestamp = "2025-01-01T00:00:00Z"
            signature = _sign_composio(webhook_id, timestamp, body, "test-secret")
            async with _make_composio_client() as client:
                with patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"):
                    second = await client.post(
                        "/api/v1/webhook/composio",
                        content=body,
                        headers={
                            "content-type": "application/json",
                            "webhook-id": webhook_id,
                            "webhook-timestamp": timestamp,
                            "webhook-signature": signature,
                        },
                    )

        assert first.json()["message"] == "Connection event accepted"
        assert "Duplicate" in second.json()["message"]
        assert expire.await_count == 1

    async def test_an_unsigned_connection_event_is_rejected_before_any_parsing(self, real_redis):
        with patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire:
            async with _make_composio_client() as client:
                with patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", "test-secret"):
                    response = await client.post(
                        "/api/v1/webhook/composio",
                        json=_make_connection_payload(),
                        headers={"webhook-id": "conn-unsigned-001"},
                    )

        assert response.status_code == 401
        expire.assert_not_awaited()

    async def test_the_endpoint_does_not_check_the_user_exists_before_dispatching(self, real_redis):
        # Whether GAIA knows this user is the transition's business, not the
        # webhook's — `expire_user_integration` already no-ops on a user with no
        # record (unit X1). Re-checking here would duplicate that guard and give
        # Composio a second way to be told "unknown", so the endpoint just acks
        # and hands the id straight through.
        stranger_id = "507f1f77bcf86cd799439099"
        integration = MagicMock()
        integration.id = "notion"

        with (
            patch.object(_endpoint(), "get_integration_by_config", return_value=integration),
            patch.object(_endpoint(), "expire_user_integration", new_callable=AsyncMock) as expire,
        ):
            response = await self._post(
                real_redis,
                _make_connection_payload(user_id=stranger_id),
                webhook_id="conn-stranger-001",
            )
            for _ in range(100):
                if expire.await_count:
                    break
                await asyncio.sleep(0)

        assert response.status_code == 200
        assert response.json()["message"] == "Connection event accepted"
        expire.assert_awaited_once()
        assert expire.await_args.args[0] == stranger_id
