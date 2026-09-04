"""Workflow utility functions for GAIA workflow system."""

import asyncio
from typing import Any, TypedDict, cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    Workflow,
)
from app.services.workflow.subagent_output import FinalizedOutput
from shared.py.wide_events import log


class WorkflowConfigError(Exception):
    pass


class WorkflowCreatedTriggerConfig(TypedDict):
    """The ``trigger_config`` block of the ``workflow_created`` stream frame."""

    type: TriggerType
    cron_expression: str | None
    trigger_name: str | None
    enabled: bool
    timezone: str | None


class WorkflowCreatedPayload(TypedDict):
    """The ``workflow_created`` frame streamed when a workflow is created
    without a confirmation card — the frontend renders it as a created-workflow
    tool card."""

    id: str | None
    title: str
    description: str
    trigger_config: WorkflowCreatedTriggerConfig
    integration_ids: list[str]
    activated: bool


async def handle_workflow_error(
    workflow_id: str,
    user_id: str,
    error: Exception,
    deactivate: bool = False,
) -> None:
    """Centralized error handling for workflow operations."""
    log.set(
        operation="handle_workflow_error",
        workflow_id=workflow_id,
        user_id=user_id,
        deactivate=deactivate,
    )
    try:
        # Imported lazily: workflow_utils is imported by app.services.workflow, which
        # the repository's ChromaDB/oauth chain reaches back into — a module-level
        # import would form a cycle.
        from app.db.repositories.workflows import workflow_repository

        await workflow_repository.mark_error(workflow_id, user_id, deactivate=deactivate)
        log.error(
            f"{LogTag.WORKFLOW} Workflow error",
            workflow_id=workflow_id,
            error=error,
            user_id=user_id,
        )
    except Exception as update_error:
        log.error(
            f"{LogTag.WORKFLOW} Failed to update workflow error state",
            workflow_id=workflow_id,
            error=str(update_error),
            error_type=type(update_error).__name__,
            user_id=user_id,
        )


def ensure_trigger_config_object(trigger_config: TriggerConfig | dict[str, Any]) -> TriggerConfig:
    """Convert dict to TriggerConfig object if needed."""
    if isinstance(trigger_config, dict):
        return TriggerConfig(**trigger_config)
    return trigger_config


# The two envelopes below stay `dict[str, Any]` rather than becoming a pair of
# TypedDicts: every workflow tool returns them straight out of a `-> dict`
# handler in agents/tools/workflow_shared_tools.py, and mypy does not accept a
# TypedDict where a plain `dict` is declared — naming the shape means retyping
# that module's tools in the same pass (Type Safety item 14).
def error_response(error_code: str, message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {"success": False, "error": error_code, "message": message}


def success_response(data: object, message: str | None = None) -> dict[str, Any]:
    """Return a standardized success response."""
    response: dict[str, Any] = {"success": True, "data": data}
    if message:
        response["message"] = message
    return response


async def _partition_integration_ids(
    integration_ids: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Split ids into (valid, unknown) by resolving each against real integrations
    (built-in, the user's custom, or the public marketplace). Resolve errors fail open
    (kept as valid) so a transient DB blip never drops a real integration."""
    from app.services.integrations.integration_resolver import IntegrationResolver

    if not integration_ids:
        return [], []
    seen = list(dict.fromkeys(i.strip().lower() for i in integration_ids if i.strip()))
    resolved = await asyncio.gather(
        *(IntegrationResolver.resolve(i) for i in seen), return_exceptions=True
    )
    valid: list[str] = []
    unknown: list[str] = []
    for iid, res in zip(seen, resolved, strict=True):
        if isinstance(res, BaseException):
            log.warning(f"{LogTag.WORKFLOW} integration_id resolve failed for", iid=iid, res=res)
            valid.append(iid)
        elif res is not None:
            valid.append(iid)
        else:
            unknown.append(iid)
    return valid, unknown


async def unknown_integration_ids(integration_ids: list[str] | None) -> list[str]:
    """Ids that do NOT resolve to any real integration in GAIA (hallucinated names)."""
    _, unknown = await _partition_integration_ids(integration_ids)
    return unknown


async def filter_existing_integration_ids(integration_ids: list[str] | None) -> list[str]:
    """Keep only integration ids that resolve to a real integration. Final backstop so a
    hallucinated id (a service that does not exist in GAIA, e.g. 'stripe') never persists."""
    valid, unknown = await _partition_integration_ids(integration_ids)
    for iid in unknown:
        log.warning(f"{LogTag.WORKFLOW} Dropping unknown integration_id from workflow", iid=iid)
    return valid


def get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config. Raises error if missing."""
    user_id: str | None = agent_configurable(config).get("user_id")
    if not user_id:
        raise WorkflowConfigError("User authentication required")
    return user_id


def get_workflow_id(config: RunnableConfig) -> str:
    """Extract workflow_id from config. Raises error if missing."""
    workflow_id: str | None = agent_configurable(config).get("workflow_id")
    if not workflow_id:
        raise WorkflowConfigError(
            "No workflow in this run's config: this tool only works inside a workflow run."
        )
    return workflow_id


def get_thread_id(config: RunnableConfig) -> str | None:
    """Extract thread_id from config."""
    thread_id: str | None = agent_configurable(config).get("thread_id")
    return thread_id


def can_create_directly(draft: FinalizedOutput) -> bool:
    """
    Check if workflow can be created directly without user confirmation.

    Returns True if direct_create flag is True and trigger type is not integration.
    Returns False if direct_create is False or trigger type is integration.
    """
    if not draft.direct_create:
        return False

    # Integration triggers ALWAYS need confirmation (have config_fields like calendar_ids, channel_ids)
    return draft.trigger_type != "integration"


async def create_workflow_directly(
    draft: FinalizedOutput,
    user_id: str,
    writer: StreamWriter,
    user_timezone: str = "UTC",
) -> dict[str, Any] | None:
    """
    Create a workflow directly from a finalized draft.

    Returns success_response on success, or None if creation fails
    (caller should fall back to streaming draft).
    """
    log.set(
        operation="create_workflow_directly",
        user_id=user_id,
        workflow_title=draft.title,
        trigger_type=draft.trigger_type,
        user_timezone=user_timezone,
    )
    try:
        from app.services.workflow.service import WorkflowService

        trigger_config = TriggerConfig(
            type=draft.backend_trigger_type,
            enabled=True,
            cron_expression=draft.cron_expression,
            trigger_name=draft.trigger_slug,
            timezone=user_timezone,
        )

        # The two fields are not interchangeable: description is the one-line card
        # copy, prompt is what the executor reads as the run's goal. Collapsing
        # them put the whole numbered instruction blob on the card.
        request = CreateWorkflowRequest(
            title=draft.title,
            description=draft.description or draft.title,
            prompt=draft.prompt or draft.description or draft.title,
            trigger_config=trigger_config,
            steps=None,
            generate_immediately=True,
            integration_ids=draft.integration_ids,
        )

        workflow = await WorkflowService.create_workflow(
            request=request,
            user_id=user_id,
            user_timezone=user_timezone,
        )

        workflow_data: WorkflowCreatedPayload = {
            "id": workflow.id,
            "title": workflow.title,
            "description": workflow.description,
            "trigger_config": {
                "type": workflow.trigger_config.type,
                "cron_expression": workflow.trigger_config.cron_expression,
                "trigger_name": workflow.trigger_config.trigger_name,
                "enabled": workflow.trigger_config.enabled,
                "timezone": workflow.trigger_config.timezone,
            },
            "integration_ids": workflow.integration_ids,
            "activated": workflow.activated,
        }

        writer({"workflow_created": workflow_data})

        log.info(f"{LogTag.WORKFLOW} Created workflow directly", id=workflow.id)

        return success_response(
            {"status": "created", "workflow_id": workflow.id},
            f"Workflow '{workflow.title}' created and activated.",
        )

    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} Direct creation failed",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None


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


def build_edit_workflow_task(workflow: Workflow, user_request: str) -> str:
    """Build the task for editing an existing workflow.

    Gives the assistant the current workflow so it can apply just the requested
    change and re-emit the FULL updated workflow as a finalized draft.
    """
    tc = workflow.trigger_config
    trigger_desc = tc.type.value
    if tc.cron_expression:
        trigger_desc += f" (cron: {tc.cron_expression}, timezone: {tc.timezone})"
    if tc.trigger_name:
        trigger_desc += f" (trigger: {tc.trigger_name})"

    return f"""Edit an existing workflow.

Current workflow:
- Title: {workflow.title}
- Description: {workflow.description}
- Trigger: {trigger_desc}
- Prompt:
{workflow.effective_prompt}

The user wants to change:
"{user_request}"

Your job:
1. Apply the requested change to produce the UPDATED workflow.
2. Keep everything the user did NOT ask to change exactly as it is.
3. If the change needs a different event trigger, call search_triggers for the right trigger_slug.
4. If anything is unclear, ask ONE clarifying question.
5. Output the finalized workflow JSON representing the FULL updated workflow.

Remember to include a JSON block in your response."""


async def _edited_fields(
    draft: FinalizedOutput, workflow: Workflow
) -> dict[str, str | list[str] | TriggerConfig]:
    """The fields an edit draft actually changes.

    The assistant re-emits the FULL workflow on every edit, so only persist
    fields that actually changed. This keeps a rename/schedule-only edit from
    rewriting the prompt and triggering an unnecessary step regeneration.
    """
    update_fields: dict[str, str | list[str] | TriggerConfig] = {}
    if draft.title and draft.title != workflow.title:
        update_fields["title"] = draft.title
    if draft.description and draft.description != (workflow.description or ""):
        update_fields["description"] = draft.description
    new_prompt = draft.prompt or draft.description
    if new_prompt and new_prompt != workflow.effective_prompt:
        update_fields["prompt"] = new_prompt
    # Drop hallucinated ids here too, so edits can't persist a fake integration the
    # create path (filter_existing_integration_ids in service.create_workflow) rejects.
    # An empty list is treated as "the draft omitted the field" rather than "clear
    # them": every other field here is guarded the same way, and a draft that
    # forgot to re-emit integration_ids must not silently strip the workflow's
    # dependencies. Integrations are removed in the workflow editor.
    if draft.integration_ids:
        filtered_integration_ids = await filter_existing_integration_ids(draft.integration_ids)
        if filtered_integration_ids != (workflow.integration_ids or []):
            update_fields["integration_ids"] = filtered_integration_ids
    return update_fields


def _edited_trigger(
    draft: FinalizedOutput, workflow: Workflow, user_timezone: str
) -> tuple[TriggerConfig | None, bool]:
    """The trigger config an edit applies, and whether the change needs the editor.

    Integration triggers carry config_fields we can't set from here, so a
    change to one is reported as needing the editor instead of applied.
    """
    new_type = draft.backend_trigger_type
    current = workflow.trigger_config
    trigger_changed = (
        new_type != current.type
        or (draft.trigger_slug or None) != (current.trigger_name or None)
        or (draft.cron_expression or None) != (current.cron_expression or None)
    )
    if not trigger_changed:
        return None, False
    if new_type == TriggerType.INTEGRATION:
        return None, True
    return (
        TriggerConfig(
            type=new_type,
            enabled=workflow.activated,
            cron_expression=draft.cron_expression,
            trigger_name=draft.trigger_slug,
            # Keep the zone the schedule was authored in. "Move it to 8am"
            # means 8am where the workflow already runs, not 8am wherever the
            # user happens to be asking from.
            timezone=current.timezone or user_timezone,
        ),
        False,
    )


async def _regenerated_after_prompt_edit(
    workflow: Workflow, user_id: str, updated: Workflow
) -> Workflow:
    """The workflow with its steps regenerated for the new prompt; the update
    already committed, so a regeneration failure is logged and ``updated``
    stands."""
    from app.services.workflow.service import WorkflowService

    try:
        regenerated = await WorkflowService.regenerate_workflow_steps(
            workflow.id or "", user_id, regeneration_reason="prompt edited via assistant"
        )
        if regenerated:
            updated = regenerated
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} Step regeneration after edit failed for",
            id=workflow.id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
    return updated


async def apply_workflow_edit(
    draft: FinalizedOutput,
    workflow: Workflow,
    user_id: str,
    writer: StreamWriter,
    user_timezone: str = "UTC",
) -> dict[str, Any]:
    """Apply a finalized edit draft to an existing workflow via WorkflowService.update_workflow.

    Applies title/description/prompt and manual/scheduled trigger changes directly.
    Integration-trigger changes are NOT applied here (their config — channels,
    repos, calendars — must be set in the app's workflow editor); the caller is
    told so the user can adjust it there.
    """
    from app.services.workflow.service import WorkflowService

    update_fields = await _edited_fields(draft, workflow)
    trigger_config, needs_editor = _edited_trigger(draft, workflow, user_timezone)
    if trigger_config is not None:
        update_fields["trigger_config"] = trigger_config

    if not update_fields:
        if needs_editor:
            return error_response(
                "needs_editor",
                "Changing an integration trigger needs its config (channels, repos, "
                "calendars, etc.), which is set in the workflow editor in the app. Ask "
                "the user to adjust the trigger there.",
            )
        return success_response(
            {"status": "unchanged", "workflow_id": workflow.id},
            "No changes to apply.",
        )

    # The splat is what gives the request its ``exclude_unset`` semantics — only
    # the keys set above are persisted. Widened back to Any for the call because
    # mypy checks a ``**`` splat field-by-field and cannot match a union value
    # type against each optional field; the narrow type above is what actually
    # guards the writes.
    updated = await WorkflowService.update_workflow(
        workflow.id or "",
        UpdateWorkflowRequest(**cast(dict[str, Any], update_fields)),
        user_id,
        user_timezone=user_timezone,
    )
    if not updated:
        return error_response("not_found", f"Workflow {workflow.id} not found")

    # A prompt change makes the existing steps stale (steps are derived from the
    # prompt). Regenerate them so the UI plan matches the new behavior. This is a
    # secondary enhancement — the field update already committed, so a regen
    # failure is logged loudly but does not fail the edit.
    if "prompt" in update_fields:
        updated = await _regenerated_after_prompt_edit(workflow, user_id, updated)

    # mode="json" — the frame is json.dumps'd by the stream writer; a native
    # datetime would raise inside the edit tool and loop the agent on retries.
    writer({"workflow_data": {"action": "updated", "workflow": updated.model_dump(mode="json")}})

    message = f"Workflow '{updated.title}' updated."
    if needs_editor:
        message += (
            " The integration trigger itself was left unchanged — its config is set "
            "in the workflow editor in the app."
        )
    return success_response({"status": "updated", "workflow_id": updated.id}, message)
