"""
Composio webhook endpoint.

Handles incoming webhooks from Composio and routes them to the appropriate handlers.
Uses the trigger registry for extensible event handling.

Each trigger handler implements its own `process_event()` method which handles:
- Finding matching workflows
- Queuing workflow execution via WorkflowQueueService

Connection-lifecycle events take a separate path: they carry none of the trigger
identifiers, and their only effect is pausing the workflows that needed the dead
integration and running the shared integration expiry transition.
"""

import asyncio
from collections.abc import Mapping
from typing import TypedDict, cast

from composio.core.models.webhook_events import is_connection_expired_event
from fastapi import APIRouter, Request
from pydantic import ValidationError

from app.config.oauth_config import get_integration_by_config, get_integration_by_toolkit
from app.constants.integrations import (
    DEAD_CONNECTION_STATUSES,
    WEBHOOK_TASK_TIMEOUT,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.webhook_models import (
    ComposioConnectionEvent,
    ComposioWebhookAckResponse,
    ComposioWebhookEvent,
    TriggerEventAccount,
)
from app.services.integrations.integration_accounts import event_account_name
from app.services.integrations.integration_expiry import announce_account_expiry, expire_account
from app.services.triggers import get_handler_by_event
from app.services.triggers.base import TriggerHandler
from app.services.workflow.integration_pause import pause_workflows_for_expired_integration
from app.utils.webhook_utils import verify_composio_webhook_signature
from shared.py.wide_events import log, spawn_logged_task

router = APIRouter()


async def _process_webhook_event(handler: TriggerHandler, event_data: ComposioWebhookEvent) -> None:
    """Background task: find matching workflows and queue them."""
    try:
        account = await event_account_name(
            event_data.user_id, event_data.type, event_data.connection_nano_id
        )
        if account is not None:
            # Lets the run act on the account that received the event, not the primary.
            event_data.data.update(TriggerEventAccount(gaia_account=account))
        await asyncio.wait_for(
            handler.process_event(
                event_type=event_data.type,
                # Handlers match against trigger_config.composio_trigger_ids, which
                # stores the trigger NANO id (ti_...); matching against `trigger_id`
                # (the internal UUID) never hits, so forward the nano id.
                trigger_id=event_data.trigger_nano_id or event_data.trigger_id,
                user_id=event_data.user_id,
                data=event_data.data,
            ),
            timeout=WEBHOOK_TASK_TIMEOUT,
        )
    except TimeoutError:
        log.error(
            f"{LogTag.COMPOSIO} Webhook background processing timed out",
            timeout_s=WEBHOOK_TASK_TIMEOUT,
            event_type=event_data.type,
            user_id=event_data.user_id,
        )
    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Webhook background processing failed",
            event_type=event_data.type,
            user_id=event_data.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )


async def _expire_connection(
    user_id: str, integration_id: str, reason: str | None, connected_account_id: str
) -> None:
    """Background task: expire the account, pause what its death halts, then tell the user.

    Pausing is the caller's job because ``integration_expiry`` cannot import the
    workflow layer without closing an import cycle (see its module docstring).
    All steps share one timeout budget.
    """
    try:
        async with asyncio.timeout(WEBHOOK_TASK_TIMEOUT):
            expired = await expire_account(
                user_id, integration_id, connected_account_id, trigger="webhook", reason=reason
            )
            if expired is None:
                return
            paused = (
                await pause_workflows_for_expired_integration(user_id, integration_id)
                if expired.stops_workflows
                else []
            )
            await announce_account_expiry(user_id, integration_id, expired, paused, reason)
    except TimeoutError:
        log.error(
            f"{LogTag.COMPOSIO} Connection expiry processing timed out",
            timeout_s=WEBHOOK_TASK_TIMEOUT,
            user_id=user_id,
            integration_id=integration_id,
        )


class _WebhookEnvelope(TypedDict, total=False):
    """A Composio delivery as it arrives, before validation; values unchecked."""

    type: object
    timestamp: object
    data: object


class _TriggerData(TypedDict, total=False):
    """The identifiers a trigger delivery's data carries; values unchecked."""

    connection_id: object
    connection_nano_id: object
    trigger_nano_id: object
    trigger_id: object
    user_id: object


def _handle_connection_event(body: Mapping[str, object]) -> ComposioWebhookAckResponse:
    """Route a Composio connection-lifecycle event onto the shared expiry transition.

    Always acknowledges: an envelope GAIA cannot parse, an integration it does not
    recognise, or a status that is not terminal are all logged and dropped, because
    a non-200 makes Composio redeliver the same unusable event indefinitely.
    """
    # Confirms the delivered shape against the SDK TypedDicts without ever
    # touching `data.state`, which carries the account's access/refresh tokens.
    envelope: _WebhookEnvelope = cast(_WebhookEnvelope, body)
    data = envelope.get("data")
    log.set_ns(
        "composio_connection",
        envelope_keys=sorted(body),
        data_keys=sorted(data) if isinstance(data, dict) else None,
    )

    try:
        event = ComposioConnectionEvent.model_validate(body)
    except ValidationError as e:
        log.error(
            f"{LogTag.COMPOSIO} Unparseable connection event — dropped",
            event_type=envelope.get("type"),
            error_type=type(e).__name__,
            error=str(e),
        )
        return ComposioWebhookAckResponse(message="Connection event not understood")

    data = event.data
    integration = get_integration_by_config(data.auth_config.id) or get_integration_by_toolkit(
        data.toolkit.slug
    )
    log.set_ns(
        "composio_connection",
        connected_account_id=data.id,
        status=data.status,
        status_reason=data.status_reason,
        toolkit=data.toolkit.slug,
        auth_config_id=data.auth_config.id,
        integration_id=integration.id if integration else None,
    )
    log.set(user={"id": data.user_id})

    if integration is None:
        log.warning(
            f"{LogTag.COMPOSIO} Connection event for an unrecognised integration — dropped",
            toolkit=data.toolkit.slug,
            auth_config_id=data.auth_config.id,
        )
        return ComposioWebhookAckResponse(message="Unknown integration ignored")

    if data.status not in DEAD_CONNECTION_STATUSES:
        log.info(
            f"{LogTag.COMPOSIO} Connection event with a live status — no expiry",
            status=data.status,
            integration_id=integration.id,
        )
        return ComposioWebhookAckResponse(message="Connection status not terminal")

    spawn_logged_task(
        "composio_connection_expiry",
        _expire_connection(data.user_id, integration.id, data.status_reason, data.id),
        user={"id": data.user_id},
        webhook={"event_type": event.type, "integration_id": integration.id},
    )

    log.set(operation="webhook_accepted", outcome="success")
    return ComposioWebhookAckResponse(message="Connection event accepted")


@router.post("/webhook/composio")
async def webhook_composio(request: Request) -> ComposioWebhookAckResponse:
    """Handle incoming Composio webhooks — trigger messages and connection lifecycle.

    Routes events to the appropriate handler based on event type.
    Returns 200 immediately; workflow matching and queueing, and the connection
    expiry transition, happen in a fire-and-forget background task.
    """
    await verify_composio_webhook_signature(request)

    # pragma: no mutate — Starlette header lookup is case-insensitive, so a
    # case change to the header name is a provable no-op.
    webhook_id = request.headers.get("webhook-id", "")  # pragma: no mutate
    if webhook_id:
        already_processed = not await redis_cache.client.set(
            f"webhook:composio:{webhook_id}", "1", nx=True, ex=3600
        )
        if already_processed:
            log.info(f"{LogTag.COMPOSIO} Duplicate webhook ignored", webhook_id=webhook_id)
            return ComposioWebhookAckResponse(message="Duplicate webhook ignored")

    body = await request.json()

    # Branch on the RAW type: ComposioWebhookEvent's validator uppercases `type`
    # and requires trigger identifiers connection events don't carry, so
    # constructing it first would raise before routing.
    if is_connection_expired_event(body):
        # The SDK type guard narrows to its ConnectionExpiredEvent TypedDict; the
        # handler re-validates the payload itself rather than trusting that shape.
        return _handle_connection_event(cast(Mapping[str, object], body))

    if not isinstance(body, dict):
        # Composio only ever sends an object, so this is malformed. Ack anyway:
        # the dedupe key is already claimed, so raising would have Composio
        # redeliver a body it can never parse.
        log.error(
            f"{LogTag.COMPOSIO} Webhook body is not a JSON object — dropped",
            body_type=type(body).__name__,
        )
        return ComposioWebhookAckResponse(message="Webhook body not understood")

    envelope: _WebhookEnvelope = cast(_WebhookEnvelope, body)
    data = envelope.get("data")
    trigger: _TriggerData = cast(_TriggerData, data if isinstance(data, dict) else {})

    event_data = ComposioWebhookEvent.model_validate(
        {
            "connection_id": trigger.get("connection_id"),
            "connection_nano_id": trigger.get("connection_nano_id"),
            "trigger_nano_id": trigger.get("trigger_nano_id"),
            "trigger_id": trigger.get("trigger_id"),
            "user_id": trigger.get("user_id"),
            "data": data,
            "timestamp": envelope.get("timestamp"),
            "type": envelope.get("type"),
        }
    )
    log.set(
        user={"id": event_data.user_id},
        webhook={"event_type": event_data.type, "trigger_id": event_data.trigger_id},
    )

    # Find handler for this event type
    handler = get_handler_by_event(event_data.type)
    if not handler:
        log.debug(f"{LogTag.COMPOSIO} Unhandled webhook type", event_type=event_data.type)
        return ComposioWebhookAckResponse(message="Webhook received")

    # Fire-and-forget: return 200 immediately, process in background
    spawn_logged_task(
        "composio_webhook_processing",
        _process_webhook_event(handler, event_data),
        user={"id": event_data.user_id},
        webhook={"event_type": event_data.type, "trigger_id": event_data.trigger_id},
    )

    log.set(operation="webhook_accepted", outcome="success")
    return ComposioWebhookAckResponse(message="Webhook accepted")
