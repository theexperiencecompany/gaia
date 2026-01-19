"""
Gmail trigger matching service for workflow automation.
Simplified to trigger on ALL emails (no pattern filtering).
"""

from typing import List

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow


async def find_matching_workflows(user_id: str) -> List[Workflow]:
    """
    Find all active email-triggered workflows for a user.
    Simplified: all email workflows match (no filtering).
    """
    try:
        query = {
            "user_id": user_id,
            "activated": True,
            "trigger_config.type": TriggerType.INTEGRATION,
            "trigger_config.trigger_name": "gmail_new_message",
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
                logger.error(f"Error processing workflow document: {e}")
                continue

        return workflows

    except Exception as e:
        logger.error(f"Error finding matching workflows: {e}")
        return []
