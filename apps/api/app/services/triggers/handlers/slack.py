"""
Slack trigger handler.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import (
    SlackChannelCreatedPayload,
    SlackListAllChannelsData,
    SlackListAllChannelsInput,
    SlackReceiveMessagePayload,
)
from app.models.trigger_configs import SlackChannelCreatedConfig, SlackNewMessageConfig
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
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
        trigger_config: TriggerConfig,
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

        trigger_data = trigger_config.trigger_data

        # Handle channel created separately
        if trigger_name == "slack_channel_created":
            if trigger_data is not None and not isinstance(
                trigger_data, SlackChannelCreatedConfig
            ):
                raise TypeError(
                    f"Expected SlackChannelCreatedConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__}"
                )
            return self._register_single_trigger_sync(
                user_id, "SLACK_CHANNEL_CREATED", {}
            )

        # Validate trigger_data type for slack_new_message
        if not isinstance(trigger_data, SlackNewMessageConfig):
            raise TypeError(
                f"Expected SlackNewMessageConfig for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
            )

        trigger_ids: List[str] = []

        # Use channel_ids list directly
        channel_ids = trigger_data.channel_ids or []

        # If no specific channels, register once for "all channels" (empty channel_id)
        if not channel_ids:
            channel_ids = [""]

        # Build list of all triggers to register
        triggers_to_register: List[tuple[str, Dict[str, Any]]] = []

        # Always register main message trigger for regular channel messages
        for channel_id in channel_ids:
            base_config: Dict[str, Any] = {}
            if channel_id:
                base_config["channel_id"] = channel_id
            triggers_to_register.append(("SLACK_RECEIVE_MESSAGE", base_config.copy()))

        # Register additional triggers for message types NOT excluded
        exclusion_map = {
            "exclude_bot_messages": "SLACK_RECEIVE_BOT_MESSAGE",
            "exclude_direct_messages": "SLACK_RECEIVE_DIRECT_MESSAGE",
            "exclude_group_messages": "SLACK_RECEIVE_GROUP_MESSAGE",
            "exclude_mpim_messages": "SLACK_RECEIVE_MPIM_MESSAGE",
            "exclude_thread_replies": "SLACK_RECEIVE_THREAD_REPLY",
        }

        for field_name, composio_slug in exclusion_map.items():
            # Logic is: if exclude_X is False (default), we register the trigger
            # If exclude_X is True, we SKIP registering it
            should_register = not getattr(trigger_data, field_name, False)

            if should_register:
                for channel_id in channel_ids:
                    base_config = {}
                    if channel_id:
                        base_config["channel_id"] = channel_id
                    triggers_to_register.append((composio_slug, base_config.copy()))

        # Register all triggers in parallel
        async def register_single(
            composio_slug: str, config: Dict[str, Any]
        ) -> List[str]:
            return await asyncio.to_thread(
                self._register_single_trigger_sync, user_id, composio_slug, config
            )

        tasks = [register_single(slug, cfg) for slug, cfg in triggers_to_register]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                trigger_ids.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Slack trigger registration failed: {result}")

        return trigger_ids

    def _register_single_trigger_sync(
        self, user_id: str, composio_slug: str, trigger_config: Dict[str, Any]
    ) -> List[str]:
        """Helper to register a single Composio trigger synchronously."""
        try:
            composio = get_composio_service()
            result = composio.composio.triggers.create(
                user_id=user_id,
                slug=composio_slug,
                trigger_config=trigger_config.copy(),
            )

            if result and hasattr(result, "trigger_id"):
                logger.info(
                    f"Registered {composio_slug} for user {user_id}: {result.trigger_id}"
                )
                return [result.trigger_id]
            return []
        except Exception as e:
            logger.error(f"Failed to register Slack trigger {composio_slug}: {e}")
            return []

        return []

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Slack trigger event."""
        try:
            # Validate payload based on event/trigger type
            try:
                if (
                    "channel_created" in event_type.lower()
                    or "channel_created" in trigger_id
                ):
                    SlackChannelCreatedPayload.model_validate(data)
                elif "message" in event_type.lower() or "message" in trigger_id:
                    SlackReceiveMessagePayload.model_validate(data)
            except Exception as e:
                logger.debug(f"Slack payload validation failed: {e}")

            query = {
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
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

                    # Get trigger_data
                    trigger_data = config_dict.get("trigger_data", {})

                    # Filter by channel_ids if specified
                    channel_ids_str = trigger_data.get("channel_ids", "")
                    if channel_ids_str:
                        # Parse comma-separated channel IDs
                        selected_channels = [
                            c.strip() for c in channel_ids_str.split(",") if c.strip()
                        ]
                        # Use typed payload model for type-safe access
                        try:
                            payload = SlackReceiveMessagePayload.model_validate(data)
                            message_channel = payload.channel or ""
                        except Exception:
                            # Fallback to dict access if validation fails
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
                    # Build params with typed model
                    input_model = SlackListAllChannelsInput(
                        limit=1000,
                        exclude_archived=True,
                        types="public_channel,private_channel,mpim,im",
                        cursor=cursor,
                        channel_name=None,
                    )

                    result: ToolExecutionResponse = await asyncio.to_thread(
                        tool.invoke, input_model.model_dump(exclude_none=True)
                    )

                    # Check response status
                    if not result["successful"]:
                        logger.error(f"Slack API error: {result['error']}")
                        break

                    data = SlackListAllChannelsData.model_validate(result["data"])
                    channels_data = data.get_channels()

                    # Add channels from this page
                    for channel in channels_data:
                        channel_id = channel.id
                        channel_name = channel.name

                        if channel_id and channel_name:
                            # Format label based on channel type
                            if channel.is_im:
                                # Direct message
                                label = f"DM: {channel_name}"
                            elif channel.is_mpim:
                                # Group DM
                                label = f"Group: {channel_name}"
                            elif channel.is_private:
                                # Private channel
                                label = f"🔒 {channel_name}"
                            else:
                                # Public channel
                                label = f"# {channel_name}"

                            all_channels.append({"value": channel_id, "label": label})

                    # Check for next page
                    cursor = data.next_cursor
                    if not cursor:
                        break

                    page_count += 1

                logger.info(f"Returning {len(all_channels)} Slack channel options")
                return all_channels

            except Exception as e:
                logger.error(f"Failed to fetch Slack channels: {e}")
                return []

        return []


slack_trigger_handler = SlackTriggerHandler()
