"""
Gmail poll trigger handler.

Handles interval-based Gmail polling using the gmail_poll_inbox trigger.

Unlike GmailTriggerHandler (which matches workflows by user_id), this handler
registers a real Composio trigger ID and matches workflows by that ID —
consistent with all other integration handlers (calendar, github, etc.).

This handler is used by system workflows that should poll Gmail on a schedule
rather than fire on every single incoming email.
"""

from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.models.trigger_configs import GmailPollInboxConfig
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError


class GmailPollTriggerHandler(TriggerHandler):
    """Interval-based Gmail polling trigger handler.

    Registers GMAIL_NEW_GMAIL_MESSAGE with a polling interval via Composio.

    Does NOT claim GMAIL_NEW_GMAIL_MESSAGE in event_types — GmailTriggerHandler
    owns that event and calls into this handler's find_workflows() for poll-based
    workflows. This avoids overwriting the event routing in the registry.
    """

    SUPPORTED_TRIGGERS = ["gmail_poll_inbox"]
    SUPPORTED_EVENTS: Set[str] = set()

    TRIGGER_TO_COMPOSIO = {
        "gmail_poll_inbox": "GMAIL_NEW_GMAIL_MESSAGE",
    }

    @property
    def trigger_names(self) -> List[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> Set[str]:
        return self.SUPPORTED_EVENTS

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> List[str]:
        """Register a polling Gmail trigger with the configured interval.

        Returns a list containing the Composio trigger ID so workflows can be
        matched by trigger_id in find_workflows().

        Raises:
            TriggerRegistrationError: If trigger registration fails
        """
        trigger_data = trigger_config.trigger_data

        if not isinstance(trigger_data, GmailPollInboxConfig):
            raise TriggerRegistrationError(
                f"Expected GmailPollInboxConfig for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__ if trigger_data else 'None'}",
                trigger_name,
            )

        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            raise TriggerRegistrationError(
                f"Unknown gmail poll trigger: {trigger_name}",
                trigger_name,
            )

        composio_config = {"interval": trigger_data.interval}

        return await self._register_triggers_parallel(
            user_id=user_id,
            trigger_name=trigger_name,
            configs=[composio_config],
            composio_slug=composio_slug,
        )

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching this polling trigger event.

        Matches by composio trigger_id, same pattern as CalendarTriggerHandler.
        """
        try:
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_id,
            }
            return await self._load_workflows_from_query(
                query,
                log_context=f"gmail_poll trigger_id={trigger_id}",
            )

        except Exception as e:
            logger.error(
                f"Error finding workflows for gmail_poll trigger {trigger_id}: {e}"
            )
            return []


gmail_poll_trigger_handler = GmailPollTriggerHandler()
