"""End-to-end webhook delivery pipeline: signed HTTP delivery → endpoint →
trigger registry → handler → workflow queueing / expiry transition.

The unit tests for this endpoint mock the signature check, the registry and the
handler, so the chain a real Composio delivery travels is never exercised in one
piece. These tests keep every link real — HMAC verification over the actual
request bytes, raw-body routing, model validation, the global trigger registry,
the Gmail handler's matching strategies, and spawn_logged_task's background
execution — and mock only the infra seams (Redis dedupe, workflow repository,
ARQ queueing, the terminal expiry services).
"""

import asyncio
import base64
import hashlib
import hmac as hmac_mod
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.config.settings import settings
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowStep
from app.services.triggers.batching import PER_EMAIL_FALLBACK_WINDOW_SECONDS
from app.services.workflow.queue_service import WorkflowQueueService
from shared.py.wide_events import spawn_logged_task

ENDPOINT = "/api/v1/webhook/composio"
MODULE = "app.api.v1.endpoints.webhook_composio"
GMAIL_HANDLER_MODULE = "app.services.triggers.handlers.gmail"

TEST_SECRET = "hermetic-webhook-secret"
USER_ID = "507f1f77bcf86cd799439011"
WORKFLOW_ID = "wf_pipeline_001"

# A real Composio auth config from oauth_config.py — the expiry path must
# resolve the integration through the REAL config, not a mocked lookup.
CALENDAR_AUTH_CONFIG_ID = "ac_exqcpnLvCzGJ"


def _sign(body: bytes, webhook_id: str, timestamp: str, secret: str) -> str:
    """The exact scheme app/utils/webhook_utils.py verifies."""
    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + body
    digest = hmac_mod.new(secret.encode(), signed, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(digest).decode()}"


def _signed_headers(body: dict[str, Any], webhook_id: str, secret: str = TEST_SECRET) -> dict:
    payload = json.dumps(body).encode()
    timestamp = "1700000000"
    return {
        "content-type": "application/json",
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": _sign(payload, webhook_id, timestamp, secret),
    }


def _gmail_delivery() -> dict:
    return {
        "type": "gmail_new_gmail_message",
        "timestamp": "2026-08-10T05:44:33Z",
        "data": {
            "connection_id": "conn-1",
            "connection_nano_id": "nano-1",
            "trigger_nano_id": "ti_nano",
            "trigger_id": "uuid-1",
            "user_id": USER_ID,
            "payload": {"message_id": "msg-1", "message_text": "hello"},
        },
    }


def _expired_connection_delivery() -> dict:
    return {
        "id": "msg_847cdfcd",
        "type": "composio.connected_account.expired",
        "timestamp": "2026-08-10T05:44:33Z",
        "data": {
            "id": "ca_xxxxxxxxxxxx",
            "user_id": USER_ID,
            "status": "EXPIRED",
            "status_reason": "refresh_token_revoked",
            "is_disabled": False,
            "toolkit": {"slug": "GOOGLECALENDAR"},
            "auth_config": {
                "id": CALENDAR_AUTH_CONFIG_ID,
                "auth_scheme": "OAUTH2",
                "is_composio_managed": True,
                "is_disabled": False,
            },
            "state": {"authScheme": "OAUTH2", "val": {"status": "EXPIRED"}},
            "data": {},
            "params": {},
            "created_at": "2026-05-02T09:12:44Z",
            "updated_at": "2026-08-10T05:44:33Z",
        },
    }


def _workflow() -> Workflow:
    return Workflow(
        id=WORKFLOW_ID,
        user_id=USER_ID,
        title="Pipeline Workflow",
        prompt="Run this workflow",
        steps=[WorkflowStep(title="Step 1", description="Do something")],
        activated=True,
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            enabled=True,
            trigger_name="gmail_new_message",
            composio_trigger_ids=[],
        ),
    )


@pytest.fixture
def _webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hermetic fence blanks the real secret; sign against a known one."""
    monkeypatch.setattr(settings, "COMPOSIO_WEBHOOK_SECRET", TEST_SECRET)


@pytest.fixture
def _redis():
    """Dedupe seam: every key is unclaimed unless a test says otherwise."""
    redis = MagicMock()
    redis.client.set = AsyncMock(return_value=True)
    with patch(f"{MODULE}.redis_cache", redis):
        yield redis


@pytest.fixture
def _spawned():
    """Keep spawn_logged_task REAL but hand back its tasks, so each test can
    await the fire-and-forget work deterministically instead of sleeping."""
    spawned: list[asyncio.Task] = []

    def _recording_spawn(operation: str, coro: Any, **ctx: Any) -> asyncio.Task:
        task = spawn_logged_task(operation, coro, **ctx)
        spawned.append(task)
        return task

    with patch(f"{MODULE}.spawn_logged_task", side_effect=_recording_spawn):
        yield spawned


async def _drain(spawned: list[asyncio.Task]) -> None:
    if spawned:
        await asyncio.wait_for(asyncio.gather(*spawned, return_exceptions=True), timeout=5)


class TestTriggerDeliveryToQueuedExecution:
    """A signed GMAIL_NEW_GMAIL_MESSAGE delivery must come out the other end as
    a queued workflow execution carrying the payload and the integration stamp."""

    async def test_a_signed_delivery_buffers_the_matched_workflow_for_a_batched_run(
        self,
        unauthenticated_client: AsyncClient,
        _webhook_secret: None,
        _redis: MagicMock,
        _spawned: list,
    ) -> None:
        """gmail_new_message fires once per inbound email, so a delivery joins the
        workflow's daily batch instead of queueing its own agent run — the direct
        per-event queue path must NOT be taken (that fan-out once spent a paying
        user's whole daily budget in three minutes)."""
        queue = AsyncMock()
        buffer = AsyncMock(return_value=True)
        body = _gmail_delivery()
        with (
            patch(
                f"{GMAIL_HANDLER_MODULE}.workflow_repository.find_active_integration_workflows",
                AsyncMock(return_value=[_workflow()]),
            ),
            # The poll-inbox strategy shares this event type but matches by
            # trigger id; no poll workflow exists in this scenario.
            patch(
                f"{GMAIL_HANDLER_MODULE}.workflow_repository.find_active_by_composio_trigger",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.tracked_todo_service.tracked_todo_service.get_signal_matching_context",
                AsyncMock(return_value="todo context"),
            ),
            patch("app.services.triggers.base.buffer_trigger_event", buffer),
            patch.object(WorkflowQueueService, "queue_workflow_execution", queue),
        ):
            response = await unauthenticated_client.post(
                ENDPOINT,
                content=json.dumps(body).encode(),
                headers=_signed_headers(body, "wh-e2e-1"),
            )
            await _drain(_spawned)

        assert response.status_code == 200
        assert response.json()["message"] == "Webhook accepted"

        buffer.assert_awaited_once()
        workflow_id, user_id, data, window_seconds, context = buffer.await_args.args
        assert workflow_id == WORKFLOW_ID
        assert user_id == USER_ID
        assert data["payload"]["message_id"] == "msg-1"
        assert window_seconds == PER_EMAIL_FALLBACK_WINDOW_SECONDS
        # The stamp that tells the worker this run came from an integration
        # trigger, not a manual "run now".
        assert context["trigger_type"] == TriggerType.INTEGRATION.value
        assert context["tracked_todos_context"] == "todo context"
        queue.assert_not_awaited()

    async def test_a_bad_signature_is_refused_and_never_reaches_the_handler(
        self,
        unauthenticated_client: AsyncClient,
        _webhook_secret: None,
        _redis: MagicMock,
        _spawned: list,
    ) -> None:
        queue = AsyncMock()
        body = _gmail_delivery()
        with (
            patch(
                f"{GMAIL_HANDLER_MODULE}.workflow_repository.find_active_integration_workflows",
                AsyncMock(),
            ),
            patch.object(WorkflowQueueService, "queue_workflow_execution", queue),
        ):
            response = await unauthenticated_client.post(
                ENDPOINT,
                content=json.dumps(body).encode(),
                headers=_signed_headers(body, "wh-e2e-bad", secret="attacker-secret"),
            )

        assert response.status_code == 401
        # A refused delivery claims no dedupe key — otherwise the real sender's
        # retry would arrive to find itself already "processed".
        _redis.client.set.assert_not_awaited()
        queue.assert_not_awaited()

    async def test_a_redelivered_webhook_id_is_processed_exactly_once(
        self,
        unauthenticated_client: AsyncClient,
        _webhook_secret: None,
        _redis: MagicMock,
        _spawned: list,
    ) -> None:
        # First delivery claims the key; Composio's retry finds it taken.
        _redis.client.set = AsyncMock(side_effect=[True, None])
        queue = AsyncMock()
        buffer = AsyncMock(return_value=True)
        body = _gmail_delivery()
        headers = _signed_headers(body, "wh-e2e-dupe")
        with (
            patch(
                f"{GMAIL_HANDLER_MODULE}.workflow_repository.find_active_integration_workflows",
                AsyncMock(return_value=[_workflow()]),
            ),
            # The poll-inbox strategy shares this event type but matches by
            # trigger id; no poll workflow exists in this scenario.
            patch(
                f"{GMAIL_HANDLER_MODULE}.workflow_repository.find_active_by_composio_trigger",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.tracked_todo_service.tracked_todo_service.get_signal_matching_context",
                AsyncMock(return_value=""),
            ),
            patch("app.services.triggers.base.buffer_trigger_event", buffer),
            patch.object(WorkflowQueueService, "queue_workflow_execution", queue),
        ):
            first = await unauthenticated_client.post(
                ENDPOINT, content=json.dumps(body).encode(), headers=headers
            )
            await _drain(_spawned)
            second = await unauthenticated_client.post(
                ENDPOINT, content=json.dumps(body).encode(), headers=headers
            )

        assert first.json()["message"] == "Webhook accepted"
        assert second.json()["message"] == "Duplicate webhook ignored"
        buffer.assert_awaited_once()
        queue.assert_not_awaited()


class TestConnectionExpiryDelivery:
    """A signed connected_account.expired delivery must resolve the integration
    through the real oauth_config and run the shared expiry transition."""

    async def test_an_expired_calendar_account_runs_the_expiry_transition(
        self,
        unauthenticated_client: AsyncClient,
        _webhook_secret: None,
        _redis: MagicMock,
        _spawned: list,
    ) -> None:
        pause = AsyncMock(return_value=3)
        expire = AsyncMock()
        body = _expired_connection_delivery()
        with (
            patch(f"{MODULE}.pause_workflows_for_expired_integration", pause),
            patch(f"{MODULE}.expire_user_integration", expire),
        ):
            response = await unauthenticated_client.post(
                ENDPOINT,
                content=json.dumps(body).encode(),
                headers=_signed_headers(body, "wh-e2e-exp"),
            )
            await _drain(_spawned)

        assert response.status_code == 200
        assert response.json()["message"] == "Connection event accepted"

        pause.assert_awaited_once_with(USER_ID, "googlecalendar")
        expire.assert_awaited_once_with(
            USER_ID,
            "googlecalendar",
            reason="refresh_token_revoked",
            trigger="webhook",
            notify=True,
            connected_account_id="ca_xxxxxxxxxxxx",
            paused_workflows=3,
        )

    async def test_an_unrecognised_toolkit_is_acked_without_touching_any_user(
        self,
        unauthenticated_client: AsyncClient,
        _webhook_secret: None,
        _redis: MagicMock,
        _spawned: list,
    ) -> None:
        pause = AsyncMock()
        expire = AsyncMock()
        body = _expired_connection_delivery()
        body["data"]["toolkit"]["slug"] = "SOME_TOOLKIT_WE_DO_NOT_HAVE"
        body["data"]["auth_config"]["id"] = "ac_unknown_config"
        with (
            patch(f"{MODULE}.pause_workflows_for_expired_integration", pause),
            patch(f"{MODULE}.expire_user_integration", expire),
        ):
            response = await unauthenticated_client.post(
                ENDPOINT,
                content=json.dumps(body).encode(),
                headers=_signed_headers(body, "wh-e2e-unk"),
            )
            await _drain(_spawned)

        assert response.json()["message"] == "Unknown integration ignored"
        pause.assert_not_awaited()
        expire.assert_not_awaited()
