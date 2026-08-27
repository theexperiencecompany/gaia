"""The one transition that marks a user's integration connection dead.

Two callers, same state change, different escalation: the Composio
connection-lifecycle webhook runs it proactively with ``notify=True`` (the user
is not looking at GAIA, so the notification and the live page update are the
whole point), and the tool-execution reconciliation path runs it with
``notify=False`` (the user is mid-conversation and is handed a connect card in
the same turn — a notification seconds later is noise).

Pausing the workflows that needed the dead integration is the *caller's* job:
it hands the paused titles in as ``paused_workflows`` and this module only
folds them into the announcement. The transition is reachable from the Composio
tool wrapper, so importing the workflow layer here would close an import cycle
(``workflow.service`` -> ``trigger_service``/``generation_service`` ->
``composio_service`` -> back to this module).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import INTEGRATION_STATUS_EXPIRED
from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.core.websocket_manager import websocket_manager
from app.db.repositories.user_integrations import user_integration_repository
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelConfig,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.services.composio.proxy_client import invalidate_connected_account_cache
from app.services.integrations.user_integration_status import update_user_integration_status
from app.services.integrations_fs import schedule_user_integrations_sync
from app.services.notification_service import notification_service
from shared.py.wide_events import log

# Which detection path drove this transition — carried into the wide event so a
# proactive expiry is distinguishable from one reconciled off a failed tool call.
ExpiryTrigger = Literal["webhook", "tool_execution"]

INTEGRATION_STATUS_UPDATE_EVENT = "integration_status_update"


@dataclass(frozen=True)
class ExpiryOptions:
    """Why the connection is being expired, and what the expiry should trigger."""

    # Required, not defaulted: every caller passes both explicitly. A default
    # `trigger` silently decides which detection path an expiry reads as, and a
    # default `notify` silently decides whether the user hears about it — both
    # are the caller's call, and neither should be inherited by omission.
    trigger: ExpiryTrigger
    notify: bool
    reason: str | None = None
    connected_account_id: str | None = None
    paused_workflows: Sequence[str] = ()


async def expire_user_integration(
    user_id: str,
    integration_id: str,
    options: ExpiryOptions,
) -> bool:
    """Mark a user's integration connection dead and stop the rest of GAIA treating it as usable.

    Returns True when the transition was applied, False when it was a no-op —
    no ``user_integrations`` record (never fabricates one) or already ``expired``
    (idempotent, so a flapping account cannot notify twice without a real
    reconnect in between).
    """
    reason = options.reason
    trigger = options.trigger
    notify = options.notify
    connected_account_id = options.connected_account_id
    paused_workflows = options.paused_workflows

    integration = get_integration_by_id(integration_id)
    toolkit = (
        integration.composio_config.toolkit if integration and integration.composio_config else None
    )

    log.set_ns(
        "integration_expiry",
        user_id=user_id,
        integration_id=integration_id,
        toolkit=toolkit,
        reason=reason,
        trigger=trigger,
        notify=notify,
        connected_account_id=connected_account_id,
    )

    record = await user_integration_repository.get_for_user(user_id, integration_id)
    if record is None:
        log.set_ns("integration_expiry", outcome="no_record")
        return False
    if record.status == INTEGRATION_STATUS_EXPIRED:
        log.set_ns("integration_expiry", outcome="already_expired")
        return False

    log.set_ns("integration_expiry", previous_status=record.status)

    # The @CacheInvalidator on update_user_integration_status busts the full
    # USER_INTEGRATION_CACHE_PATTERNS set (oauth_status + tools:user:* +
    # tool_namespaces), so the next status read recomputes from Mongo.
    await update_user_integration_status(
        user_id,
        integration_id,
        INTEGRATION_STATUS_EXPIRED,
        expired_reason=reason,
        connected_account_id=connected_account_id,
    )
    invalidate_connected_account_cache(user_id, toolkit)
    schedule_user_integrations_sync(user_id)

    log.set_ns("integration_expiry", outcome="expired", paused_workflows=len(paused_workflows))
    log.warning(
        f"{LogTag.INTEGRATION} Integration connection expired",
        user_id=user_id,
        integration_id=integration_id,
        toolkit=toolkit,
        previous_status=record.status,
        reason=reason,
        trigger=trigger,
        paused_workflows=len(paused_workflows),
    )

    if notify or paused_workflows:
        await _announce_expiry(
            user_id,
            integration_id,
            integration.name if integration else integration_id,
            paused_workflows,
            reason,
        )

    return True


# Composio never enumerates `status_reason`: the pinned SDK types it as a bare
# `Optional[str]` on both the webhook payload (`composio.core.models.webhook_events`)
# and the REST response. `refresh_token_revoked` is the only value we have observed,
# so this matches meaningful tokens rather than a guessed enum \u2014 grow it as new
# values show up in the `integration_expiry.reason` wide-event field.
_EXPIRY_CAUSE_BY_TOKEN: tuple[tuple[str, str], ...] = (
    ("revoked", "Your {integration} account revoked GAIA's access."),
    ("expired", "The sign-in for your {integration} account expired."),
)


def _expiry_cause(integration_name: str, reason: str | None) -> str | None:
    """Human copy for why the connection died, or None when the reason is unrecognised.

    Only a single machine token is ever interpreted: the tool-execution path passes
    a raw Composio error sentence as the reason, and developer text must never reach
    user-facing copy.
    """
    if not reason:
        return None
    token = reason.strip().lower()
    if len(token.split()) != 1:
        return None
    for marker, template in _EXPIRY_CAUSE_BY_TOKEN:
        if marker in token:
            return template.format(integration=integration_name)
    return None


def _expiry_body(integration_name: str, paused_workflows: Sequence[str], reason: str | None) -> str:
    """Say what actually stopped working \u2014 and why, when the reason is one we recognise."""
    lead = _expiry_cause(integration_name, reason) or (
        f"GAIA lost access to your {integration_name} account and can no longer use it."
    )
    if not paused_workflows:
        return f"{lead} Reconnect to pick up where you left off."
    if len(paused_workflows) == 1:
        return (
            f"{lead} Your \u201c{paused_workflows[0]}\u201d workflow is paused until you reconnect."
        )
    return f"{lead} {len(paused_workflows)} workflows are paused until you reconnect."


async def _announce_expiry(
    user_id: str,
    integration_id: str,
    integration_name: str,
    paused_workflows: Sequence[str],
    reason: str | None,
) -> None:
    """Flip an open integrations page live, then leave a persistent Reconnect nudge."""
    await websocket_manager.broadcast_to_user(
        user_id=user_id,
        message={
            "type": INTEGRATION_STATUS_UPDATE_EVENT,
            "data": {"integration_id": integration_id, "status": INTEGRATION_STATUS_EXPIRED},
        },
    )

    await notification_service.create_notification(
        NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.INTEGRATION_EXPIRED,
            type=NotificationType.WARNING,
            channels=[ChannelConfig(channel_type=CHANNEL_TYPE_INAPP)],
            content=NotificationContent(
                title=f"{integration_name} disconnected",
                body=_expiry_body(integration_name, paused_workflows, reason),
                actions=[
                    NotificationAction(
                        type=ActionType.REDIRECT,
                        label="Reconnect",
                        style=ActionStyle.PRIMARY,
                        config=ActionConfig(
                            redirect=RedirectConfig(
                                url=f"/integrations?id={integration_id}",
                                open_in_new_tab=False,
                                close_notification=True,
                            )
                        ),
                    )
                ],
            ),
            metadata={
                "integration_id": integration_id,
                "paused_workflows": len(paused_workflows),
            },
        )
    )
