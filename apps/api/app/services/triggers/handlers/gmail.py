"""
Gmail trigger handler.

Handles the account-level Gmail triggers: new inbox messages and mail the user sent.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar, NamedTuple

from pydantic import BaseModel, ValidationError

from app.constants.log_tags import LogTag
from app.constants.triggers import GMAIL_EMAIL_SENT_COMPOSIO_SLUG, GMAIL_EMAIL_SENT_TRIGGER_NAME
from app.db.repositories.workflows import workflow_repository
from app.models.composio_schemas import GmailEmailSentPayload, GmailNewMessagePayload
from app.models.webhook_models import ComposioTriggerEventIds
from app.models.workflow_models import TriggerConfig, Workflow
from app.services.triggers.base import TriggerHandler
from app.services.triggers.scope_catalog import TRIGGER_CONFIG_CLASSES
from shared.py.wide_events import log


class _GmailEvent(NamedTuple):
    trigger_name: str
    payload_model: type[BaseModel]


# One Composio event per GAIA trigger: both are account-level, so the event type is
# the only thing that keeps a sent-mail watch from waking on inbound mail.
_EVENTS: Mapping[str, _GmailEvent] = MappingProxyType(
    {
        "GMAIL_NEW_GMAIL_MESSAGE": _GmailEvent("gmail_new_message", GmailNewMessagePayload),
        GMAIL_EMAIL_SENT_COMPOSIO_SLUG: _GmailEvent(
            GMAIL_EMAIL_SENT_TRIGGER_NAME, GmailEmailSentPayload
        ),
    }
)


class GmailTriggerHandler(TriggerHandler):
    """Handler for Gmail triggers.

    Gmail triggers differ from other integrations in that they match workflows
    by user_id rather than by trigger_id, since Gmail uses account-level triggers
    via Composio (no per-resource registration like calendars).
    """

    SUPPORTED_TRIGGERS: ClassVar[list[str]] = [event.trigger_name for event in _EVENTS.values()]

    SUPPORTED_EVENTS: ClassVar[set[str]] = set(_EVENTS)

    @property
    def trigger_names(self) -> list[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> set[str]:
        return self.SUPPORTED_EVENTS

    def trigger_names_for_event(self, event_type: str) -> list[str]:
        return [_EVENTS[event_type].trigger_name]

    @property
    def registers_instances(self) -> bool:
        # Composio fires both Gmail triggers on the connected account (armed once
        # at connect), not on a per-owner instance — register() has no ids to return.
        return False

    async def register(
        self,
        _user_id: str,
        owner_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> list[str]:
        """Gmail triggers are automatically handled by Composio connection.

        No explicit registration needed - triggers fire on connected account.
        """
        trigger_data = trigger_config.trigger_data
        expected = TRIGGER_CONFIG_CLASSES[trigger_name]

        if trigger_data is not None and not isinstance(trigger_data, expected):
            raise TypeError(
                f"Expected {expected.__name__} for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__}"
            )

        log.info(f"{LogTag.TRIGGER} Gmail trigger enabled", owner_id=owner_id)
        return []  # No explicit trigger IDs for Gmail

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, object]
    ) -> list[Workflow]:
        """Find workflows for a Gmail event.

        Matches the event's own account-level trigger by user_id, and
        gmail_poll_inbox workflows by composio_trigger_ids — the poll trigger
        shares the GMAIL_NEW_GMAIL_MESSAGE Composio event.
        """
        log.set_ns("trigger", integration_id="gmail", trigger_type=event_type)
        try:
            try:
                _EVENTS[event_type].payload_model.model_validate(data)
            except ValidationError as e:
                log.debug(
                    f"{LogTag.TRIGGER} Gmail payload validation failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )

            user_id = ComposioTriggerEventIds.model_validate(data).user_id
            if not user_id and not trigger_id:
                log.error(f"{LogTag.TRIGGER} Gmail webhook has neither user_id nor trigger_id")
                return []

            workflows: list[Workflow] = []

            # Account-level workflows are matched only by user_id. Poll webhooks may
            # omit user_id, so only run this when we have one.
            if user_id:
                workflows.extend(
                    await workflow_repository.find_active_integration_workflows(
                        user_id, self.trigger_names_for_event(event_type)
                    )
                )

            # gmail_poll_inbox workflows match by trigger id alone — Composio's poll
            # webhooks frequently arrive with an empty user_id, and gating on it dropped every event.
            if trigger_id:
                workflows.extend(
                    await workflow_repository.find_active_by_composio_trigger(
                        trigger_id, trigger_name="gmail_poll_inbox"
                    )
                )

            return workflows

        except Exception as e:
            log.error(
                f"{LogTag.TRIGGER} Error finding Gmail workflows",
                error=str(e),
                error_type=type(e).__name__,
                trigger_id=trigger_id,
            )
            return []


gmail_trigger_handler = GmailTriggerHandler()
