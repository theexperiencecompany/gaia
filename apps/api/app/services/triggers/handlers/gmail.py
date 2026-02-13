"""
Gmail trigger handler.

Handles Gmail new message trigger processing.
"""

from typing import Any, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import GmailNewMessagePayload
from app.models.trigger_configs import GmailNewMessageConfig
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.redis_utils import RedisPoolManager


class GmailTriggerHandler(TriggerHandler):
    """Handler for Gmail triggers.

    Gmail triggers differ from other integrations in that they match workflows
    by user_id rather than by trigger_id, since Gmail uses account-level triggers
    via Composio (no per-resource registration like calendars).
    """

    SUPPORTED_TRIGGERS = ["gmail_new_message"]

    SUPPORTED_EVENTS = {"GMAIL_NEW_GMAIL_MESSAGE"}

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
        """Gmail triggers are automatically handled by Composio connection.

        No explicit registration needed - triggers fire on connected account.
        """
        trigger_data = trigger_config.trigger_data

        # Validate trigger_data type if provided
        if trigger_data is not None and not isinstance(
            trigger_data, GmailNewMessageConfig
        ):
            raise TypeError(
                f"Expected GmailNewMessageConfig for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__}"
            )

        logger.info(f"Gmail trigger enabled for workflow {workflow_id}")
        return []  # No explicit trigger IDs for Gmail

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows with Gmail triggers for a user.

        Unlike other handlers that match by trigger_id, Gmail matches by user_id
        since Gmail triggers are account-level (all emails trigger all Gmail workflows).
        """
        try:
            # Validate payload structure (for logging/debugging purposes primarily)
            # We still rely on user_id from the top-level data dict for now as it might be an envelope field
            try:
                GmailNewMessagePayload.model_validate(data)
            except Exception as e:
                logger.debug(f"Gmail payload validation failed: {e}")

            user_id = data.get("user_id")
            if not user_id:
                logger.error("No user_id in Gmail webhook data")
                return []

            query = {
                "user_id": user_id,
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.trigger_name": {"$in": self.SUPPORTED_TRIGGERS},
                "trigger_config.enabled": True,
            }

            cursor = workflows_collection.find(query)
            workflows = []

            async for workflow_doc in cursor:
                try:
                    workflow_doc["id"] = workflow_doc.get("_id")
                    if "_id" in workflow_doc:
                        del workflow_doc["_id"]
                    workflow = Workflow(**workflow_doc)
                    workflows.append(workflow)
                except Exception as e:
                    logger.error(f"Error processing workflow: {e}")
                    continue

            return workflows

        except Exception as e:
            logger.error(f"Error finding Gmail workflows: {e}")
            return []

    async def process_event(
        self,
        event_type: str,
        trigger_id: Optional[str],
        user_id: Optional[str],
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Process Gmail webhook: run workflows AND trigger email analysis."""
        workflow_result = await super().process_event(
            event_type, trigger_id, user_id, data
        )

        if user_id and event_type == "GMAIL_NEW_GMAIL_MESSAGE":
            try:
                pool = await RedisPoolManager.get_pool()
                payload = data.get("payload", data)
                message_id = (
                    payload.get("message_id")
                    or payload.get("messageId")
                    or data.get("message_id")
                )

                if message_id:
                    await pool.enqueue_job(
                        "process_email_analysis_and_replies",
                        user_id,
                        message_id,
                        {
                            "subject": payload.get("subject", ""),
                            "sender": payload.get("sender", payload.get("from", "")),
                            "date": payload.get(
                                "message_timestamp", payload.get("messageTimestamp", "")
                            ),
                            "content": payload.get(
                                "message_text", payload.get("messageText", "")
                            ),
                            "thread_id": payload.get(
                                "thread_id", payload.get("threadId")
                            ),
                        },
                    )
                    logger.info(f"Queued email analysis for message {message_id}")
            except Exception as e:
                logger.error(f"Failed to queue email analysis: {e}")

        return workflow_result


gmail_trigger_handler = GmailTriggerHandler()
