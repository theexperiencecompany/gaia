"""
Slack trigger handler.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler
from composio.types import ToolExecutionResponse


class SlackTriggerHandler(TriggerHandler):
    """Handler for Slack triggers."""

    SUPPORTED_TRIGGERS = [
        "slack_new_message",
        "slack_channel_created",
    ]

    SUPPORTED_EVENTS = {
        "SLACK_RECEIVE_MESSAGE",
        "SLACK_RECEIVE_BOT_MESSAGE",
        "SLACK_RECEIVE_DIRECT_MESSAGE",
        "SLACK_RECEIVE_GROUP_MESSAGE",
        "SLACK_RECEIVE_MPIM_MESSAGE",
        "SLACK_RECEIVE_THREAD_REPLY",
        "SLACK_CHANNEL_CREATED",
    }

    EXCLUSION_TO_TRIGGER = {
        "exclude_bot_messages": "SLACK_RECEIVE_BOT_MESSAGE",
        "exclude_direct_messages": "SLACK_RECEIVE_DIRECT_MESSAGE",
        "exclude_group_messages": "SLACK_RECEIVE_GROUP_MESSAGE",
        "exclude_mpim_messages": "SLACK_RECEIVE_MPIM_MESSAGE",
        "exclude_thread_replies": "SLACK_RECEIVE_THREAD_REPLY",
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
        config: Dict[str, Any],
    ) -> List[str]:
        """
        Register Slack triggers based on user exclusion settings.

        For each message type NOT excluded, registers the corresponding
        specific Composio trigger. Always registers SLACK_RECEIVE_MESSAGE
        for regular channel messages.
        """
        if trigger_name not in self.SUPPORTED_TRIGGERS:
            logger.error(f"Unknown Slack trigger: {trigger_name}")
            return []

        # Handle channel created separately
        if trigger_name == "slack_channel_created":
            return await self._register_single_trigger(
                user_id, "SLACK_CHANNEL_CREATED", {}
            )

        trigger_ids: List[str] = []

        # Base config (channel_id if provided)
        base_config: Dict[str, Any] = {}
        if "channel_id" in config and config["channel_id"]:
            base_config["channel_id"] = config["channel_id"]

        # Always register main message trigger for regular channel messages
        regular_msg_ids = await self._register_single_trigger(
            user_id, "SLACK_RECEIVE_MESSAGE", base_config
        )
        trigger_ids.extend(regular_msg_ids)

        # Register additional triggers for message types NOT excluded
        for exclude_key, composio_slug in self.EXCLUSION_TO_TRIGGER.items():
            if not config.get(exclude_key, False):  # NOT excluded
                additional_ids = await self._register_single_trigger(
                    user_id, composio_slug, base_config
                )
                trigger_ids.extend(additional_ids)

        return trigger_ids

    async def _register_single_trigger(
        self, user_id: str, composio_slug: str, trigger_config: Dict[str, Any]
    ) -> List[str]:
        """Helper to register a single Composio trigger."""
        try:
            composio = get_composio_service()
            result = await asyncio.to_thread(
                composio.composio.triggers.create,
                user_id=user_id,
                slug=composio_slug,
                trigger_config=trigger_config.copy(),
            )

            if result and hasattr(result, "trigger_id"):
                logger.info(
                    f"Registered {composio_slug} for user {user_id}: {result.trigger_id}"
                )
                return [result.trigger_id]
        except Exception as e:
            logger.error(f"Failed to register {composio_slug}: {e}")

        return []

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister all Slack triggers for a workflow."""
        if not trigger_ids:
            return True

        success = True
        composio = get_composio_service()

        for trigger_id in trigger_ids:
            try:
                await asyncio.to_thread(
                    composio.composio.triggers.disable,
                    trigger_id=trigger_id,
                )
                logger.info(f"Unregistered Slack trigger: {trigger_id}")
            except Exception as e:
                logger.error(f"Failed to unregister Slack trigger {trigger_id}: {e}")
                success = False

        return success

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Slack trigger event."""
        try:
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.APP,
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_id,
            }

            cursor = workflows_collection.find(query)
            workflows: List[Workflow] = []

            async for workflow_doc in cursor:
                try:
                    workflow_doc["id"] = workflow_doc.get("_id")
                    if "_id" in workflow_doc:
                        del workflow_doc["_id"]
                    workflow = Workflow(**workflow_doc)

                    # Get trigger config
                    trigger_config = workflow.trigger_config
                    if hasattr(trigger_config, "dict"):
                        config_dict = trigger_config.dict()
                    else:
                        config_dict = dict(trigger_config)

                    # Filter by channel_ids if specified
                    channel_ids_str = config_dict.get("channel_ids", "")
                    if channel_ids_str:
                        # Parse comma-separated channel IDs
                        selected_channels = [
                            c.strip() for c in channel_ids_str.split(",") if c.strip()
                        ]
                        message_channel = data.get("channel") or data.get(
                            "channel_id", ""
                        )

                        # If channels specified and message not in list, skip
                        if (
                            selected_channels
                            and message_channel not in selected_channels
                        ):
                            logger.debug(
                                f"Message channel {message_channel} not in selected channels for workflow {workflow.id}"
                            )
                            continue

                    workflows.append(workflow)
                except Exception as e:
                    logger.error(f"Error processing workflow document: {e}")
                    continue

            return workflows

        except Exception as e:
            logger.error(f"Error finding workflows for trigger {trigger_id}: {e}")
            return []

    async def get_config_options(
        self,
        trigger_name: str,
        field_name: str,
        user_id: str,
        integration_id: str,
        parent_ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, str]]:
        """Get dynamic options for Slack trigger config fields."""
        if trigger_name == "slack_new_message" and field_name == "channel_ids":
            # Fetch Slack channels list with pagination
            try:
                composio_service = get_composio_service()

                # Use SLACK_LIST_ALL_CHANNELS with pagination support
                tool = composio_service.get_tool(
                    "SLACK_LIST_ALL_CHANNELS", user_id=user_id
                )
                if not tool:
                    logger.error("Slack list all channels tool not found")
                    return []

                all_channels = []
                cursor = None
                max_pages = 10  # Prevent infinite loops
                page_count = 0

                while page_count < max_pages:
                    # Build params with all channel types and pagination
                    params: Dict[str, Any] = {
                        "limit": 1000,  # Max allowed by Slack API
                        "exclude_archived": True,
                        # Include all channel types
                        "types": "public_channel,private_channel,mpim,im",
                    }

                    if cursor:
                        params["cursor"] = cursor

                    # Invoke the tool
                    result: ToolExecutionResponse = await asyncio.to_thread(
                        tool.invoke, params
                    )

                    # Check if successful
                    if not result.get("successful", False):
                        logger.error(
                            f"Slack API error: {result.get('error', 'Unknown error')}"
                        )
                        break

                    # Extract channels from data
                    # Response structure: {data: {ok, channels: [...], response_metadata}}
                    data = result.get("data", {})

                    if not isinstance(data, dict):
                        logger.error("Unexpected data format from Slack API")
                        break

                    # Check if API call was successful
                    if not data.get("ok", False):
                        logger.error(
                            f"Slack API returned ok=false: {data.get('error')}"
                        )
                        break

                    channels = data.get("channels", [])

                    # Add channels from this page
                    for channel in channels:
                        if not isinstance(channel, dict):
                            continue

                        channel_id = channel.get("id")
                        channel_name = channel.get("name")

                        if channel_id and channel_name:
                            # Format label based on channel type
                            if channel.get("is_im"):
                                # Direct message - use different formatting
                                label = f"DM: {channel_name}"
                            elif channel.get("is_mpim"):
                                # Group DM
                                label = f"Group: {channel_name}"
                            elif channel.get("is_private"):
                                # Private channel
                                label = f"🔒 {channel_name}"
                            else:
                                # Public channel
                                label = f"# {channel_name}"

                            all_channels.append({"value": channel_id, "label": label})

                    # Check for next page
                    response_metadata = data.get("response_metadata", {})
                    next_cursor = (
                        response_metadata.get("next_cursor")
                        if isinstance(response_metadata, dict)
                        else None
                    )

                    if not next_cursor:
                        # No more pages
                        break

                    cursor = next_cursor
                    page_count += 1

                logger.info(f"Returning {len(all_channels)} Slack channel options")
                return all_channels

            except Exception as e:
                logger.error(f"Failed to fetch Slack channels: {e}")
                return []

        return []


slack_trigger_handler = SlackTriggerHandler()
