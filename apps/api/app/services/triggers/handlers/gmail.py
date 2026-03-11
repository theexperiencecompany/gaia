"""
Gmail trigger handler.

Handles Gmail new message trigger processing.
"""

import re
from html import unescape
from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import GmailNewMessagePayload
from app.models.trigger_configs import GmailNewMessageConfig
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.workflow.queue_service import WorkflowQueueService
from app.services.triggers.base import TriggerHandler


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

    @staticmethod
    def _normalize_message_text(raw_text: str) -> tuple[str, bool]:
        """Return compact plain-text message content.

        If input looks like HTML, convert it to readable plain text to reduce
        token usage in workflow context.
        """

        text = raw_text.strip()
        if not text:
            return "", False

        looks_html = bool(re.search(r"<[a-zA-Z][^>]*>", text))
        if not looks_html:
            return text, False

        parsed = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        parsed = re.sub(r"(?i)<br\s*/?>", "\n", parsed)
        parsed = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", parsed)
        parsed = re.sub(r"(?i)<li[^>]*>", "- ", parsed)
        parsed = re.sub(r"(?s)<[^>]+>", " ", parsed)
        parsed = unescape(parsed)
        parsed = re.sub(r"[\t\r\f\v]+", " ", parsed)
        parsed = re.sub(r"\n{3,}", "\n\n", parsed)
        parsed = re.sub(r" +", " ", parsed)

        return parsed.strip(), True

    @staticmethod
    def _build_trigger_context(data: Dict[str, Any]) -> Dict[str, Any]:
        """Build compact Gmail trigger context for workflow execution."""
        message_text_raw = data.get("message_text", "")
        message_text = (
            message_text_raw
            if isinstance(message_text_raw, str)
            else str(message_text_raw or "")
        )
        message_text, parsed_from_html = GmailTriggerHandler._normalize_message_text(
            message_text
        )
        preview = message_text.replace("\n", " ").strip()

        return {
            "type": "gmail",
            "source": "gmail",
            "triggered_at": data.get("message_timestamp"),
            "email_data": {
                "message_id": data.get("message_id"),
                "thread_id": data.get("thread_id"),
                "sender": data.get("sender", "Unknown"),
                "subject": data.get("subject", "No Subject"),
                "message_text": message_text[:4000],
                "preview": preview[:400],
                "content_note": (
                    "parsed_plain_text_from_html" if parsed_from_html else "plain_text"
                ),
            },
            "trigger_data": {
                "message_id": data.get("message_id"),
                "thread_id": data.get("thread_id"),
                "sender": data.get("sender"),
                "subject": data.get("subject"),
                "message_timestamp": data.get("message_timestamp"),
            },
        }

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
        """Find workflows for a Gmail event.

        Handles two matching strategies in one pass:
        1. gmail_new_message workflows — matched by user_id (account-level, no trigger IDs)
        2. gmail_poll_inbox workflows — matched by composio_trigger_ids (per-interval triggers)

        Both are routed here because they share the GMAIL_NEW_GMAIL_MESSAGE Composio event.
        """
        try:
            try:
                GmailNewMessagePayload.model_validate(data)
            except Exception as e:
                logger.debug(f"Gmail payload validation failed: {e}")

            user_id = data.get("user_id")
            if not user_id:
                logger.error("No user_id in Gmail webhook data")
                return []

            workflows: List[Workflow] = []

            # Strategy 1: match gmail_new_message workflows by user_id
            user_query = {
                "user_id": user_id,
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.trigger_name": {"$in": self.SUPPORTED_TRIGGERS},
                "trigger_config.enabled": True,
            }

            # Strategy 2: match gmail_poll_inbox workflows by trigger_id
            poll_query = {
                "user_id": user_id,
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.trigger_name": "gmail_poll_inbox",
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_id,
            }

            for query in (user_query, poll_query):
                async for workflow_doc in workflows_collection.find(query):
                    try:
                        workflow_doc["id"] = workflow_doc.get("_id")
                        if "_id" in workflow_doc:
                            del workflow_doc["_id"]
                        workflows.append(Workflow(**workflow_doc))
                    except Exception as e:
                        logger.error(f"Error processing workflow: {e}")

            return workflows

        except Exception as e:
            logger.error(f"Error finding Gmail workflows: {e}")
            return []

    async def process_event(
        self,
        event_type: str,
        trigger_id: str | None,
        user_id: str | None,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Process Gmail events with compact trigger context for workflows."""
        workflows = await self.find_workflows(event_type, trigger_id or "", data)

        if not workflows:
            logger.info(f"No matching workflows for event: {event_type}")
            return {"status": "success", "message": "No matching workflows"}

        trigger_context = self._build_trigger_context(data)
        queued_count = 0

        for workflow in workflows:
            try:
                if workflow.id is None:
                    logger.error("Workflow has no id, skipping")
                    continue

                await WorkflowQueueService.queue_workflow_execution(
                    workflow.id,
                    workflow.user_id,
                    context=trigger_context,
                )
                queued_count += 1
                logger.info(f"Queued workflow {workflow.id} for event {event_type}")
            except Exception as e:
                logger.error(f"Failed to queue workflow {workflow.id}: {e}")

        return {
            "status": "success",
            "message": f"Queued {queued_count} workflows",
        }


gmail_trigger_handler = GmailTriggerHandler()
