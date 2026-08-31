"""
Workflow conversation service for managing single conversations per workflow.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from langchain_core.messages import ToolCall

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import (
    MessageModel,
    SystemPurpose,
    ToolDataEntry,
    UpdateMessagesRequest,
)
from app.models.message_models import SelectedWorkflowData
from app.models.playbook_models import PlaybookDocument, PlaybookStep
from app.models.user_models import AuthenticatedUser
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import Workflow
from app.services.conversation_service import (
    create_system_conversation,
    update_messages,
)
from app.utils.agent_utils import format_tool_call_entry
from app.utils.stream_utils import apply_outputs_to_tool_data
from shared.py.wide_events import log

# A workflow reuses one conversation across all runs; cap it so the doc can't grow
# past MongoDB's 16MB limit (and fail every run with WriteError 17419).
WORKFLOW_CONVERSATION_MAX_MESSAGES = 50


async def get_or_create_workflow_conversation(
    workflow_id: str, user_id: str, workflow_title: str
) -> str:
    """Get the workflow's existing conversation id, or create one bound to it."""
    # Reuse the existing workflow conversation if one already exists.
    existing = await conversation_repository.find_workflow_conversation(user_id, workflow_id)
    if existing is not None:
        return existing.conversation_id

    conversation = await create_system_conversation(
        user_id=user_id,
        description=workflow_title,
        system_purpose=SystemPurpose.WORKFLOW_EXECUTION,
    )

    # Tag the new conversation with its workflow binding (source + metadata).
    await conversation_repository.set_workflow_binding(
        conversation.conversation_id,
        user_id=user_id,
        workflow_id=workflow_id,
        workflow_title=workflow_title,
    )

    return conversation.conversation_id


async def add_workflow_execution_messages(
    conversation_id: str,
    workflow_execution_messages: list[MessageModel],
    user_id: str,
) -> None:
    """Append execution messages to the workflow's conversation."""
    try:
        # Create update request
        messages_request = UpdateMessagesRequest(
            conversation_id=conversation_id, messages=workflow_execution_messages
        )

        user_dict: AuthenticatedUser = {"user_id": user_id}
        await update_messages(
            messages_request, user_dict, max_messages=WORKFLOW_CONVERSATION_MAX_MESSAGES
        )

    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Failed to store messages in conversation",
            conversation_id=conversation_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        raise


def build_selected_workflow_data(workflow: Workflow) -> SelectedWorkflowData:
    """The workflow card a run's trigger message carries.

    One builder for both run paths: the agent turn and the playbook replay must
    attach the identical card, or the same workflow renders two different ways
    depending on how it happened to run.
    """
    return SelectedWorkflowData(
        id=workflow.id,
        title=workflow.title,
        description=workflow.description,
        prompt=workflow.prompt,
        steps=[
            {
                "id": step.id,
                "title": step.title,
                "description": step.description,
                "category": step.category,
            }
            for step in workflow.steps
        ],
    )


async def add_playbook_run_messages(
    conversation_id: str,
    user_id: str,
    workflow: Workflow,
    response: str,
    trace: Sequence[RecordedCall],
    playbook: PlaybookDocument,
) -> None:
    """Write a replayed run into the workflow's conversation as a normal turn.

    The calls render exactly as the live path renders them, led by a Run
    playbook card so the reader can tell WHY the run finished in seconds: the
    steps were replayed from the workflow's playbook, not reasoned out. Without
    that provenance an instant run with two cards reads as broken, not fast.
    """
    trigger_message = MessageModel(
        type="user",
        response="",
        date=datetime.now(UTC).isoformat(),
        message_id=str(uuid4()),
        selectedWorkflow=build_selected_workflow_data(workflow),
    )
    result_message = MessageModel(
        type="bot",
        response=response,
        date=datetime.now(UTC).isoformat(),
        message_id=str(uuid4()),
        tool_data=await build_playbook_tool_data(trace, user_id, playbook),
    )
    await add_workflow_execution_messages(
        conversation_id=conversation_id,
        workflow_execution_messages=[trigger_message, result_message],
        user_id=user_id,
    )


def _playbook_plan(steps: Sequence[PlaybookStep]) -> list[str]:
    """The frozen steps as lines a person can read on the Run playbook card.

    "todos subagent -> list_todos" says who does what; the raw document shape
    (ids, args, nesting) belongs in read_playbook, not on a chat card.
    """
    lines: list[str] = []
    for step in steps:
        if step.handoff:
            children = ", ".join(child.tool or "?" for child in step.steps)
            lines.append(f"{step.handoff} subagent -> {children}")
        else:
            lines.append(step.tool or "?")
    return lines


async def build_playbook_tool_data(
    trace: Sequence[RecordedCall], user_id: str, playbook: PlaybookDocument
) -> list[ToolDataEntry]:
    """Replayed calls in the shape ``drain_executor_tool_data`` yields.

    Built through ``format_tool_call_entry`` rather than by hand so a card's
    category, icon and display name are resolved by the one function the live
    stream uses. The synthetic call ids exist only to carry each result back
    onto its own entry through the same backfill the live path runs.
    """
    entries: list[ToolDataEntry] = []
    outputs: dict[str, str] = {}
    lead_id = str(uuid4())
    plan = _playbook_plan(playbook.steps)
    lead = await format_tool_call_entry(
        ToolCall(
            name="run_playbook",
            args={"description": playbook.description, "plan": plan},
            id=lead_id,
        ),
        user_id=user_id,
    )
    if lead is not None:
        outputs[lead_id] = f"Replayed {len(plan)} frozen step(s): " + "; ".join(plan)
        entries.append(lead)
    for call in trace:
        call_id = str(uuid4())
        entry = await format_tool_call_entry(
            ToolCall(name=call.tool_name, args=call.args, id=call_id),
            user_id=user_id,
        )
        if entry is None:
            continue
        if call.subagent_id:
            entry["subagent_id"] = call.subagent_id
        outputs[call_id] = call.result_digest
        entries.append(entry)
    apply_outputs_to_tool_data(entries, outputs, only_tool_name="tool_calls_data")
    return entries
