"""The one transition that marks a user's connected account dead.

Two callers, same state change, different escalation: the Composio
connection-lifecycle webhook runs it and then announces it (the user is not
looking at GAIA, so the notification and the live page update are the whole
point), and the tool-execution reconciliation path runs it silently (the user is
mid-conversation and is handed a connect card in the same turn).

The integration itself only reads as expired once every account has died.
Pausing workflows is the *caller's* job, decided off the returned outcome: the
transition is reachable from the Composio tool wrapper, so importing the
workflow layer here would close an import cycle (workflow.service ->
trigger_service/generation_service -> composio_service -> back to this module).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import INTEGRATION_STATUS_UPDATE_EVENT
from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.core.websocket_manager import websocket_manager
from app.models.integration_models import IntegrationAccount
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
from app.services.integrations.integration_accounts import (
    get_account_record,
    primary_account,
    save_accounts,
)
from app.services.integrations_fs import schedule_user_integrations_sync
from app.services.notification_service import notification_service
from shared.py.wide_events import log

# Which detection path drove this transition — carried into the wide event so a
# proactive expiry is distinguishable from one reconciled off a failed tool call.
ExpiryTrigger = Literal["webhook", "tool_execution"]


@dataclass(frozen=True)
class AccountExpired:
    account: IntegrationAccount
    account_count: int
    was_primary: bool
    # Every account is now dead, so the integration itself reads expired.
    integration_expired: bool

    @property
    def stops_workflows(self) -> bool:
        """Workflow triggers live on the primary, so its death halts them even with others alive."""
        return self.integration_expired or self.was_primary


async def expire_account(
    user_id: str,
    integration_id: str,
    connected_account_id: str | None,
    *,
    trigger: ExpiryTrigger,
    reason: str | None = None,
) -> AccountExpired | None:
    """Mark one account dead (None names the primary); None when nothing changed.

    No-ops: no record (never fabricates one), an account GAIA does not track (a
    superseded or legacy one), or one already expired (idempotent, so a flapping
    account cannot notify twice without a real reconnect in between).
    """
    log.set_ns(
        "integration_expiry",
        user_id=user_id,
        integration_id=integration_id,
        reason=reason,
        trigger=trigger,
        connected_account_id=connected_account_id,
    )
    record = await get_account_record(user_id, integration_id)
    if record is None:
        log.set_ns("integration_expiry", outcome="no_record")
        return None
    account = (
        record.find_account(connected_account_id)
        if connected_account_id
        else primary_account(record)
    )
    if account is None:
        log.set_ns("integration_expiry", outcome="untracked_account")
        return None
    if account.status == "expired":
        log.set_ns("integration_expiry", outcome="already_expired")
        return None

    dead = account.model_copy(
        update={"status": "expired", "expired_at": datetime.now(UTC), "expired_reason": reason}
    )
    accounts = [dead if a is account else a for a in record.accounts]
    saved = await save_accounts(
        user_id, integration_id, accounts, record.primary_account_id, expired_reason=reason
    )
    schedule_user_integrations_sync(user_id)

    outcome = AccountExpired(
        account=dead,
        account_count=len(accounts),
        was_primary=record.primary_account_id == account.connected_account_id,
        integration_expired=saved.status == "expired",
    )
    log.set_ns(
        "integration_expiry",
        outcome="expired",
        was_primary=outcome.was_primary,
        integration_expired=outcome.integration_expired,
    )
    log.warning(
        f"{LogTag.INTEGRATION} Connected account expired",
        user_id=user_id,
        integration_id=integration_id,
        reason=reason,
        trigger=trigger,
        integration_expired=outcome.integration_expired,
    )
    return outcome


# Composio types `status_reason` as a bare `Optional[str]` (SDK's webhook
# payload and REST response); `refresh_token_revoked` is the only value
# observed, so this matches known tokens rather than a guessed enum.
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


async def announce_account_expiry(
    user_id: str,
    integration_id: str,
    expired: AccountExpired,
    paused_workflows: Sequence[str],
    reason: str | None,
) -> None:
    """Flip an open integrations page live, then leave a persistent Reconnect nudge."""
    integration = get_integration_by_id(integration_id)
    integration_name = integration.name if integration else integration_id
    await websocket_manager.broadcast_to_user(
        user_id=user_id,
        message={
            "type": INTEGRATION_STATUS_UPDATE_EVENT,
            "data": {
                "integration_id": integration_id,
                "status": "expired" if expired.integration_expired else "connected",
            },
        },
    )

    named = (
        f"{integration_name} ({expired.account.display_name})"
        if expired.account_count > 1
        else integration_name
    )
    await notification_service.create_notification(
        NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.INTEGRATION_EXPIRED,
            type=NotificationType.WARNING,
            channels=[ChannelConfig(channel_type=CHANNEL_TYPE_INAPP)],
            content=NotificationContent(
                title=f"{named} disconnected",
                body=_expiry_body(named, paused_workflows, reason),
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
