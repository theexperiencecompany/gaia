"""
GitHub trigger handler.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler
from composio.types import ToolExecutionResponse


class GitHubTriggerHandler(TriggerHandler):
    """Handler for GitHub triggers."""

    SUPPORTED_TRIGGERS = [
        "github_commit_event",
        "github_pr_event",
        "github_star_added",
        "github_issue_added",
    ]

    SUPPORTED_EVENTS = {
        "GITHUB_COMMIT_EVENT",
        "GITHUB_PULL_REQUEST_EVENT",
        "GITHUB_STAR_ADDED_EVENT",
        "GITHUB_ISSUE_ADDED_EVENT",
    }

    TRIGGER_TO_COMPOSIO = {
        "github_commit_event": "GITHUB_COMMIT_EVENT",
        "github_pr_event": "GITHUB_PULL_REQUEST_EVENT",
        "github_star_added": "GITHUB_STAR_ADDED_EVENT",
        "github_issue_added": "GITHUB_ISSUE_ADDED_EVENT",
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
        """Get dynamic options for GitHub trigger config fields."""
        try:
            composio_service = get_composio_service()

            # Get pagination params if provided
            page = int(kwargs.get("page", 1))
            search_query = kwargs.get("search", "").strip()

            # Use LangChain wrapper pattern
            tool = composio_service.get_tool(
                "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
                user_id=user_id,
            )
            if not tool:
                logger.error("GitHub list repositories tool not found")
                return []

            # Invoke tool with pagination params
            params = {"per_page": 100, "page": page}
            result: ToolExecutionResponse = await asyncio.to_thread(tool.invoke, params)

            # Check if successful
            if not result.get("successful", False):
                logger.error(
                    f"GitHub API error: {result.get('error', 'Unknown error')}"
                )
                return []

            # Extract repositories from data
            data = result.get("data", {})
            repos = []

            # Handle different response formats
            repos = data.get("repositories", data.get("data", []))

            # Filter by search query if provided
            if search_query:
                search_lower = search_query.lower()
                repos = [
                    r
                    for r in repos
                    if "full_name" in r and search_lower in r["full_name"].lower()
                ]

            # Convert to options format
            options = []
            for repo in repos:
                if "full_name" in repo:
                    options.append(
                        {"value": repo["full_name"], "label": repo["full_name"]}
                    )

            logger.info(f"Returning {len(options)} GitHub repository options")
            return options

        except Exception as e:
            logger.error(f"Failed to get GitHub options: {e}")
            return []

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        config: Dict[str, Any],
    ) -> List[str]:
        """Register GitHub triggers."""
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown GitHub trigger: {trigger_name}")
            return []

        composio = get_composio_service()
        trigger_config: Dict[str, Any] = {}

        if "owner" in config and "repo" in config:
            trigger_config["owner"] = config["owner"]
            trigger_config["repo"] = config["repo"]

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
            logger.error(f"Failed to register GitHub trigger {trigger_name}: {e}")
            return []

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister GitHub triggers."""
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
                logger.info(f"Unregistered GitHub trigger: {trigger_id}")
            except Exception as e:
                logger.error(f"Failed to unregister GitHub trigger {trigger_id}: {e}")
                success = False

        return success

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a GitHub trigger event."""
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


github_trigger_handler = GitHubTriggerHandler()
