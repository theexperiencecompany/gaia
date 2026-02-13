"""
Utility functions for workflow tools.

Provides:
- Standardized response helpers (error_response, success_response)
- Config extractors (get_user_id, get_thread_id, get_user_time, get_user_timezone)
- Direct workflow creation logic (can_create_directly, create_workflow_directly)
"""

from datetime import datetime, timezone
from typing import Any, Optional

from app.config.loggers import general_logger as logger
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
)
from app.services.workflow import WorkflowService
from app.services.workflow.subagent_output import FinalizedOutput
from langchain_core.runnables.config import RunnableConfig


def error_response(error_code: str, message: str) -> dict:
    """Return a standardized error response."""
    return {"success": False, "error": error_code, "message": message}


def success_response(data: Any, message: str | None = None) -> dict:
    """Return a standardized success response."""
    response = {"success": True, "data": data}
    if message:
        response["message"] = message
    return response


def get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config. Raises error if missing."""
    user_id = config.get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("User authentication required")
    return user_id


def get_thread_id(config: RunnableConfig) -> str | None:
    """Extract thread_id from config."""
    return config.get("configurable", {}).get("thread_id")


def get_user_time(config: RunnableConfig) -> datetime:
    """Extract user_time from config or return current time (always timezone-aware UTC)."""
    user_time_str = config.get("configurable", {}).get("user_time")
    if user_time_str:
        try:
            parsed = datetime.fromisoformat(user_time_str.replace("Z", "+00:00"))
            # Normalize to UTC: if aware, convert to UTC; if naive, attach UTC
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
            else:
                return parsed.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            pass
    return datetime.now(timezone.utc)


def get_user_timezone(config: RunnableConfig) -> str:
    """Extract user_timezone from config. Falls back to +00:00 (UTC)."""
    return config.get("configurable", {}).get("user_timezone", "+00:00")


def can_create_directly(draft: FinalizedOutput) -> bool:
    """
    Check if workflow can be created directly without user confirmation.

    Returns True if:
    - direct_create flag is True
    - Trigger type is manual or scheduled (no config_fields needed)

    Returns False if:
    - direct_create is False
    - Trigger type is integration (requires user to specify config like calendar_ids)
    """
    if not draft.direct_create:
        return False

    # Integration triggers ALWAYS need confirmation (have config_fields like calendar_ids, channel_ids)
    if draft.trigger_type == "integration":
        return False

    return True


async def create_workflow_directly(
    draft: FinalizedOutput,
    user_id: str,
    writer,
    user_timezone: str = "UTC",
) -> Optional[dict]:
    """
    Create a workflow directly from a finalized draft.

    Returns success_response on success, or None if creation fails
    (caller should fall back to streaming draft).
    """
    try:
        # Map frontend trigger_type to backend TriggerType enum
        # Frontend uses "scheduled", backend uses TriggerType.SCHEDULE
        trigger_type_map = {
            "manual": TriggerType.MANUAL,
            "scheduled": TriggerType.SCHEDULE,
            "integration": TriggerType.INTEGRATION,
        }
        backend_trigger_type = trigger_type_map.get(
            draft.trigger_type, TriggerType.MANUAL
        )

        # Build trigger config with timezone
        trigger_config = TriggerConfig(
            type=backend_trigger_type,
            enabled=True,
            cron_expression=draft.cron_expression,
            trigger_name=draft.trigger_slug,
            timezone=user_timezone,
        )

        workflow_description = draft.prompt if draft.prompt else draft.description

        request = CreateWorkflowRequest(
            title=draft.title,
            description=workflow_description,
            trigger_config=trigger_config,
            steps=None,  # Steps are embedded in the prompt
            generate_immediately=True,
        )

        # Create the workflow
        workflow = await WorkflowService.create_workflow(
            request=request,
            user_id=user_id,
            user_timezone=user_timezone,
        )

        # Stream workflow_created event with full workflow data
        # Map backend trigger type back to frontend format
        frontend_trigger_type_map = {
            "manual": "manual",
            "schedule": "scheduled",
            "integration": "integration",
        }

        workflow_data = {
            "id": workflow.id,
            "title": workflow.title,
            "description": workflow.description,
            "trigger_config": {
                "type": frontend_trigger_type_map.get(
                    workflow.trigger_config.type, workflow.trigger_config.type
                ),
                "cron_expression": workflow.trigger_config.cron_expression,
                "trigger_name": workflow.trigger_config.trigger_name,
                "enabled": workflow.trigger_config.enabled,
                "timezone": workflow.trigger_config.timezone,
            },
            "activated": workflow.activated,
        }

        writer({"workflow_created": workflow_data})

        logger.info(f"[create_workflow] Created workflow directly: {workflow.id}")

        return success_response(
            {"status": "created", "workflow_id": workflow.id},
            f"Workflow '{workflow.title}' created and activated.",
        )

    except Exception as e:
        logger.warning(f"[create_workflow] Direct creation failed: {e}")
        return None  # Signal to caller to fall back to draft


def build_new_workflow_task(user_request: str) -> str:
    """Build task description for a new workflow from natural language request."""
    return f"""Create a workflow based on this user request:
"{user_request}"

Your job:
1. Understand what the user wants
2. If the trigger is event-based (new email, PR created, etc.), call search_triggers to find the right trigger_slug
3. If anything is unclear, ask ONE clarifying question
4. When you have everything, output the finalized workflow JSON

Remember to include a JSON block in your response."""


def build_from_conversation_task(context, user_request: str | None = None) -> str:
    """Build task description for workflow extracted from conversation."""
    steps_text = "\n".join(
        f"- {step.get('title', step)}" if isinstance(step, dict) else f"- {step}"
        for step in context.workflow_steps
    )

    integrations = (
        ", ".join(context.integrations_used) if context.integrations_used else "None"
    )

    user_instruction = ""
    if user_request and user_request.strip():
        user_instruction = f'\n\nUser also said: "{user_request.strip()}"'

    return f"""Save this conversation as a workflow.

Suggested title: {context.suggested_title}
Summary: {context.summary}
Integrations used: {integrations}

Steps performed:
{steps_text}
{user_instruction}

Your job:
1. Use the extracted steps as the workflow steps
2. If the trigger is event-based, call search_triggers to find the right trigger_slug
3. If the user mentioned a schedule (e.g., "every Monday"), use scheduled trigger
4. If nothing is specified about when to run, ask the user
5. Output the finalized workflow JSON

Remember to include a JSON block in your response."""
