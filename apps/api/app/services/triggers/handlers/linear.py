"""
Linear trigger handler.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set, TypedDict

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler
from composio.types import ToolExecutionResponse


class LinearMember(TypedDict):
    id: str
    name: str
    email: str


class LinearTeam(TypedDict):
    id: str
    key: str
    name: str
    members: List[LinearMember]


class LinearResponseData(TypedDict):
    teams: List[LinearTeam]


# The tool used is LINEAR_GET_ALL_LINEAR_TEAMS which returns GetAllTeamsResponseWrapper
# data field is LinearResponseData which strictly contains 'teams'


class LinearTriggerHandler(TriggerHandler):
    """Handler for Linear triggers."""

    SUPPORTED_TRIGGERS = [
        "linear_issue_created",
        "linear_comment_added",
    ]

    SUPPORTED_EVENTS = {
        "LINEAR_ISSUE_CREATED_TRIGGER",
        "LINEAR_COMMENT_EVENT_TRIGGER",
    }

    TRIGGER_TO_COMPOSIO = {
        "linear_issue_created": "LINEAR_ISSUE_CREATED_TRIGGER",
        "linear_comment_added": "LINEAR_COMMENT_EVENT_TRIGGER",
    }

    @property
    def trigger_names(self) -> List[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> Set[str]:
        return self.SUPPORTED_EVENTS

    async def get_config_options(
        self,
        trigger_name: str,
        field_name: str,
        user_id: str,
        integration_id: str,
        parent_ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Get dynamic options for Linear trigger config fields."""
        try:
            composio_service = get_composio_service()

            if field_name == "team_id":
                # Use the correct tool name: LINEAR_GET_ALL_LINEAR_TEAMS
                tool = composio_service.get_tool(
                    "LINEAR_GET_ALL_LINEAR_TEAMS", user_id=user_id
                )
                if not tool:
                    logger.error("Linear get all teams tool not found")
                    return []

                # Invoke the tool
                result: ToolExecutionResponse = await asyncio.to_thread(tool.invoke, {})

                # Check if successful
                if not result.get("successful", False):
                    logger.error(
                        f"Linear API error: {result.get('error', 'Unknown error')}"
                    )
                    return []

                # Extract teams from data
                # Response structure: {data: {teams: [{id, name, key, members}]}}
                data = result.get("data", {})

                if not isinstance(data, dict):
                    logger.error("Unexpected data format from Linear API")
                    return []

                teams = data.get("teams", [])

                # Convert to options format
                options = []
                for team in teams:
                    if not isinstance(team, dict):
                        continue

                    team_id = team.get("id")
                    team_name = team.get("name")

                    if team_id and team_name:
                        options.append({"value": team_id, "label": team_name})

                logger.info(f"Returning {len(options)} Linear team options")
                return options

            return []

        except Exception as e:
            logger.error(f"Failed to get Linear options for {field_name}: {e}")
            return []

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        config: Dict[str, Any],
    ) -> List[str]:
        """Register Linear triggers."""
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown Linear trigger: {trigger_name}")
            return []

        composio = get_composio_service()
        trigger_config: Dict[str, Any] = {}

        if "team_id" in config:
            trigger_config["team_id"] = config["team_id"]

        try:
            result = await asyncio.to_thread(
                composio.composio.triggers.create,
                user_id=user_id,
                slug=composio_slug,
                trigger_config=trigger_config,
            )

            if result and hasattr(result, "trigger_id"):
                logger.info(
                    f"Registered {composio_slug} for user {user_id}: {result.trigger_id}"
                )
                return [result.trigger_id]

            return []

        except Exception as e:
            logger.error(f"Failed to register Linear trigger {trigger_name}: {e}")
            return []

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister Linear triggers."""
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
                logger.info(f"Unregistered Linear trigger: {trigger_id}")
            except Exception as e:
                logger.error(f"Failed to unregister Linear trigger {trigger_id}: {e}")
                success = False

        return success

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Linear trigger event."""
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
                    workflows.append(workflow)
                except Exception as e:
                    logger.error(f"Error processing workflow document: {e}")
                    continue

            return workflows

        except Exception as e:
            logger.error(f"Error finding workflows for trigger {trigger_id}: {e}")
            return []


linear_trigger_handler = LinearTriggerHandler()
