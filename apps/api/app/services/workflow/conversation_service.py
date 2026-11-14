"""Workflow conversation service for managing single conversations per workflow."""

from collections.abc import Sequence
from uuid import uuid4

from langchain_core.messages import ToolCall

from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import (
    SystemPurpose,
    ToolDataEntry,
)
from app.models.conversation_frame_models import StreamPayload, ToolDataEvent, ToolOutputEvent
from app.models.conversation_log_models import Notice
from app.models.message_models import SelectedWorkflowData
from app.models.playbook_models import PlaybookDocument, PlaybookStep
from app.models.stream_events import ToolOutputPayload
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import Workflow
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.tool_cards import fold_cards
from app.services.conversation_service import (
    create_system_conversation,
)
from app.utils.agent_utils import format_tool_call_entry


async def get_or_create_workflow_conversation(
    workflow_id: str, user_id: str, workflow_title: str
) -> str:
    """Get the workflow's existing conversation id, or create one bound to it."""
    # Reuse the existing workflow conversation if one already exists.
    if existing := await conversation_repository.find_workflow_conversation_id(
        user_id, workflow_id
    ):
        return existing

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


def build_selected_workflow_data(workflow: Workflow) -> SelectedWorkflowData:
    """Build the workflow card a run's trigger message carries.

    One builder for both run paths: the agent turn and the playbook replay must
    attach the identical card, or the same workflow renders two different ways
    depending on how it happened to run.
    """
    return SelectedWorkflowData(
        id=workflow.id,
        title=workflow.title,
        description=workflow.description,
        prompt=workflow.prompt,
        steps=list(workflow.steps),
    )


async def log_playbook_run(
    conversation_id: str, user_id: str, workflow: Workflow, response: str
) -> None:
    """Log what a replayed run delivered in the workflow's conversation; its cards are on its WorkFinished."""
    notice = Notice(
        id=f"playbook:{uuid4()}",
        text=response,
        origin=f'workflow "{workflow.title}" (id {workflow.id}), replayed from its playbook',
    )
    await accept(runtime_ports(), conversation_id, user_id, notice)


def _playbook_plan(steps: Sequence[PlaybookStep]) -> list[str]:
    """Render the frozen steps as tool names for the Run playbook card; the full shape belongs in read_playbook."""
    return [step.tool for step in steps]


async def build_playbook_tool_data(
    trace: Sequence[RecordedCall], user_id: str, playbook: PlaybookDocument
) -> list[ToolDataEntry]:
    """Replayed calls folded as live work's cards fold, led by a Run playbook card.

    Built by format_tool_call_entry, the live stream's formatter; synthetic call ids carry results back.
    """
    payloads: list[StreamPayload] = []
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
        payloads.append(ToolDataEvent(tool_data=lead))
        summary = f"Replayed {len(plan)} frozen step(s): " + "; ".join(plan)
        payloads.append(_output(lead_id, summary))
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
        payloads.extend((ToolDataEvent(tool_data=entry), _output(call_id, call.result_digest)))
    return list(fold_cards(payloads).tool_data)


def _output(tool_call_id: str, output: str) -> ToolOutputEvent:
    return ToolOutputEvent(tool_output=ToolOutputPayload(tool_call_id=tool_call_id, output=output))
