"""
Gmail trigger handler.

Handles Gmail new message trigger processing.
"""

from typing import Any, ClassVar

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.composio_schemas import GmailNewMessagePayload
from app.models.trigger_configs import GmailNewMessageConfig
from app.models.workflow_models import TriggerConfig, Workflow
from app.services.triggers.base import TriggerHandler
from shared.py.wide_events import log


class GmailTriggerHandler(TriggerHandler):
    """Handler for Gmail triggers.

    Gmail triggers differ from other integrations in that they match workflows
    by user_id rather than by trigger_id, since Gmail uses account-level triggers
    via Composio (no per-resource registration like calendars).
    """

    SUPPORTED_TRIGGERS: ClassVar[list[str]] = ["gmail_new_message"]

    SUPPORTED_EVENTS: ClassVar[set[str]] = {"GMAIL_NEW_GMAIL_MESSAGE"}

    @property
    def trigger_names(self) -> list[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> set[str]:
        return self.SUPPORTED_EVENTS

    @property
    def registers_instances(self) -> bool:
        # Composio fires GMAIL_NEW_GMAIL_MESSAGE on the connected account, not on a
        # per-owner instance — register() has no ids to return, and never has.
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

        # Validate trigger_data type if provided
        if trigger_data is not None and not isinstance(trigger_data, GmailNewMessageConfig):
            raise TypeError(
                f"Expected GmailNewMessageConfig for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__}"
            )

        log.info(f"{LogTag.TRIGGER} Gmail trigger enabled", owner_id=owner_id)
        return []  # No explicit trigger IDs for Gmail

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, Any]
    ) -> list[Workflow]:
        """Find workflows for a Gmail event.

        Handles two matching strategies in one pass:
        1. gmail_new_message workflows — matched by user_id (account-level, no trigger IDs)
        2. gmail_poll_inbox workflows — matched by composio_trigger_ids (per-interval triggers)

        Both are routed here because they share the GMAIL_NEW_GMAIL_MESSAGE Composio event.
        """
        log.set_ns("trigger", integration_id="gmail", trigger_type=event_type)
        try:
            try:
                GmailNewMessagePayload.model_validate(data)
            except Exception as e:
                log.debug(
                    f"{LogTag.TRIGGER} Gmail payload validation failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )

            user_id = data.get("user_id")
            if not user_id and not trigger_id:
                log.error(f"{LogTag.TRIGGER} Gmail webhook has neither user_id nor trigger_id")
                return []

            workflows: list[Workflow] = []

            # Strategy 1: gmail_new_message workflows are account-level (no trigger
            # IDs), so they can only be matched by user_id. Poll webhooks may omit
            # user_id, so only run this strategy when we actually have one.
            if user_id:
                workflows.extend(
                    await workflow_repository.find_active_integration_workflows(
                        user_id, self.SUPPORTED_TRIGGERS
                    )
                )

            # Strategy 2: gmail_poll_inbox workflows are matched by their registered
            # trigger id. The id uniquely identifies the workflow (and its owner), so
            # we do NOT gate on user_id here — Composio's poll webhooks frequently
            # arrive with an empty user_id, and gating on it dropped every event.
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
