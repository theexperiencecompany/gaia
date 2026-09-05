"""Stress: webhook replay — duplicate delivery of the same signed payload.

Real code under test:
1. The Composio webhook endpoint (``app/api/v1/endpoints/webhook_composio.py``)
   with the REAL HMAC-SHA256 signature verification (``webhook_utils``) and the
   REAL ``webhook-id`` dedup claim (``SET webhook:composio:{id} NX EX 3600``).
   The endpoint is exercised over HTTP via the ASGI test client; Redis is an
   in-process fake with genuine SET-NX semantics, so exactly-one-claim is
   deterministic. Handlers are faked (they reach into workflow queueing).
2. ``PaymentWebhookService.process_webhook``
   (``app/services/payments/payment_webhook_service.py``) — Dodo payment
   webhooks dedup on ``webhook_id`` against the processed-webhook store.
   Repositories are stateful fakes; the handler logic is the real code.

The invariant everywhere: duplicate delivery — sequential or concurrent —
produces exactly one side effect.
"""

import asyncio
import base64
import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.payment_models import SubscriptionDocument
from app.services.payments.payment_webhook_service import payment_webhook_service

pytestmark = pytest.mark.stress

WEBHOOK_URL = "/api/v1/webhook/composio"
WEBHOOK_SECRET = "stress-test-secret"
TIMESTAMP = "2025-01-01T00:00:00Z"


class _FakeRedisClient:
    """In-process Redis stand-in with real SET-NX semantics.

    No ``await`` between the existence check and the set — exactly like Redis's
    single-threaded command execution, so of N concurrent claims precisely one
    sees ``True``.
    """

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    async def set(
        self, name: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and name in self._keys:
            return None
        self._keys[name] = value
        return True

    async def delete(self, *names: str) -> int:
        return sum(self._keys.pop(name, None) is not None for name in names)


def _sign_composio(webhook_id: str, timestamp: str, body: bytes, secret: str) -> str:
    """Real signature per ``app/utils/webhook_utils.py``: HMAC-SHA256 over
    ``webhook_id.timestamp.body``, base64-encoded, prefixed ``v1,``."""
    signed_content = webhook_id.encode() + b"." + timestamp.encode() + b"." + body
    digest = hmac.new(secret.encode(), signed_content, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(digest).decode()}"


def _composio_payload(event_type: str = "GMAIL_NEW_GMAIL_MESSAGE") -> dict[str, Any]:
    return {
        "data": {
            "connection_id": "conn-123",
            "connection_nano_id": "nano-123",
            "trigger_nano_id": "trig-123",
            "trigger_id": "trigger-001",
            "user_id": "test-user",
        },
        "timestamp": TIMESTAMP,
        "type": event_type,
    }


def _signed_delivery(
    webhook_id: str, event_type: str = "GMAIL_NEW_GMAIL_MESSAGE"
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(_composio_payload(event_type)).encode()
    headers = {
        "content-type": "application/json",
        "webhook-id": webhook_id,
        "webhook-timestamp": TIMESTAMP,
        "webhook-signature": _sign_composio(webhook_id, TIMESTAMP, body, WEBHOOK_SECRET),
    }
    return body, headers


def _webhook_handler() -> MagicMock:
    handler = MagicMock()
    handler.process_event = AsyncMock(return_value=None)
    return handler


async def _settle_webhook_handler(handler: MagicMock) -> None:
    """The endpoint acks before its fire-and-forget handler task runs; yield
    until the handler has been invoked (mirrors tests/integration/real/test_webhook_composio.py)."""
    for _ in range(1000):
        if handler.process_event.await_count:
            break
        await asyncio.sleep(0)
    await asyncio.sleep(0)


class TestComposioWebhookReplay:
    async def test_duplicate_delivery_of_the_same_signed_payload_is_processed_once(
        self, client: AsyncClient
    ):
        webhook_id = "wh-replay-001"
        body, headers = _signed_delivery(webhook_id)
        handler = _webhook_handler()
        fake_redis = _FakeRedisClient()

        with (
            patch("app.db.redis.redis_cache.redis", fake_redis),
            patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", WEBHOOK_SECRET),
            patch(
                "app.api.v1.endpoints.webhook_composio.get_handler_by_event", return_value=handler
            ),
        ):
            first = await client.post(WEBHOOK_URL, content=body, headers=headers)
            await _settle_webhook_handler(handler)
            second = await client.post(WEBHOOK_URL, content=body, headers=headers)
            await _settle_webhook_handler(handler)

        assert first.status_code == 200
        assert first.json()["message"] == "Webhook accepted"
        assert second.status_code == 200
        assert second.json()["message"] == "Duplicate webhook ignored"
        handler.process_event.assert_awaited_once()

    async def test_concurrent_duplicate_deliveries_claim_exactly_once(self, client: AsyncClient):
        """Two webhooks racing to claim the same id: the SET-NX dedup lets
        exactly one through — the double-claims invariant at the webhook edge."""
        webhook_id = "wh-replay-race-001"
        body, headers = _signed_delivery(webhook_id)
        handler = _webhook_handler()
        fake_redis = _FakeRedisClient()

        with (
            patch("app.db.redis.redis_cache.redis", fake_redis),
            patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", WEBHOOK_SECRET),
            patch(
                "app.api.v1.endpoints.webhook_composio.get_handler_by_event", return_value=handler
            ),
        ):
            first, second = await asyncio.gather(
                client.post(WEBHOOK_URL, content=body, headers=headers),
                client.post(WEBHOOK_URL, content=body, headers=headers),
            )
            await _settle_webhook_handler(handler)

        messages = sorted([first.json()["message"], second.json()["message"]])
        assert messages == ["Duplicate webhook ignored", "Webhook accepted"]
        handler.process_event.assert_awaited_once()

    async def test_same_payload_with_different_webhook_ids_is_not_deduplicated(
        self, client: AsyncClient
    ):
        """Dedup keys on the delivery id, not the payload: two genuinely
        distinct deliveries of the same content are both legitimate."""
        handler = _webhook_handler()
        fake_redis = _FakeRedisClient()

        with (
            patch("app.db.redis.redis_cache.redis", fake_redis),
            patch("app.config.settings.settings.COMPOSIO_WEBHOOK_SECRET", WEBHOOK_SECRET),
            patch(
                "app.api.v1.endpoints.webhook_composio.get_handler_by_event", return_value=handler
            ),
        ):
            for webhook_id in ("wh-distinct-001", "wh-distinct-002"):
                body, headers = _signed_delivery(webhook_id)
                response = await client.post(WEBHOOK_URL, content=body, headers=headers)
                assert response.json()["message"] == "Webhook accepted"
                await _settle_webhook_handler(handler)

        assert handler.process_event.await_count == 2


class _FakeProcessedWebhookRepository:
    """Stateful store: once marked, is_processed stays True — the dedup guard."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.marked: list[str] = []

    async def is_processed(self, webhook_id: str) -> bool:
        return webhook_id in self._seen

    async def mark_processed(
        self,
        webhook_id: str,
        *,
        event_type: str,
        status: str,
        message: str | None = None,
        payment_id: str | None = None,
        subscription_id: str | None = None,
    ) -> None:
        self._seen.add(webhook_id)
        self.marked.append(webhook_id)


class _FakeSubscriptionRepository:
    """Stateful store for the subscription the handler creates."""

    def __init__(self) -> None:
        self.created: list[SubscriptionDocument] = []

    async def get_by_dodo_id(self, dodo_id: str) -> SubscriptionDocument | None:
        return next((sub for sub in self.created if sub.dodo_subscription_id == dodo_id), None)

    async def create(self, doc: SubscriptionDocument) -> SubscriptionDocument:
        self.created.append(doc)
        return doc


def _dodo_subscription_active_payload() -> dict[str, Any]:
    return {
        "business_id": "biz_123",
        "type": "subscription.active",
        "timestamp": TIMESTAMP,
        "data": {
            "subscription_id": "sub_xyz789",
            "product_id": "prod_abc123",
            "customer": {
                "customer_id": "cus_1",
                "email": "billing@example.com",
                "name": "Billing User",
            },
            "billing": {
                "city": "SF",
                "country": "US",
                "state": "CA",
                "street": "1 Main",
                "zipcode": "94105",
            },
            "status": "active",
            "currency": "usd",
            "quantity": 1,
            "recurring_pre_tax_amount": 2000,
            "payment_frequency_count": 1,
            "payment_frequency_interval": "month",
            "subscription_period_count": 1,
            "subscription_period_interval": "month",
            "created_at": TIMESTAMP,
            "metadata": {"user_id": "user-1"},
        },
    }


class TestDodoWebhookReplay:
    async def test_replayed_subscription_active_webhook_creates_one_subscription(self):
        payload = _dodo_subscription_active_payload()
        processed_repo = _FakeProcessedWebhookRepository()
        subs_repo = _FakeSubscriptionRepository()
        track = MagicMock()
        invalidate_cache = AsyncMock()

        with (
            patch(
                "app.services.payments.payment_webhook_service.processed_webhook_repository",
                processed_repo,
            ),
            patch(
                "app.services.payments.subscription_activation.subscription_repository",
                subs_repo,
            ),
            patch(
                "app.services.payments.subscription_activation.user_repository.get",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.payments.payment_webhook_service.payment_service.invalidate_plan_cache_by_dodo_id",
                invalidate_cache,
            ),
            patch(
                "app.services.payments.subscription_activation.track_subscription_event",
                track,
            ),
        ):
            first = await payment_webhook_service.process_webhook(payload, "wh_dodo_001")
            second = await payment_webhook_service.process_webhook(payload, "wh_dodo_001")

        assert first.status == "processed"
        assert first.message == "Subscription activated"
        assert second.status == "ignored"
        assert second.message == "Webhook already processed"
        assert len(subs_repo.created) == 1
        assert subs_repo.created[0].dodo_subscription_id == "sub_xyz789"
        assert processed_repo.marked == ["wh_dodo_001"]
        track.assert_called_once()
        invalidate_cache.assert_awaited_once()
