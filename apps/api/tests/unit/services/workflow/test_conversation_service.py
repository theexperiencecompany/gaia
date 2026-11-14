"""Unit tests for app.services.workflow.conversation_service."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.core.registry import init_tool_registry
from app.core.lazy_loader import providers
from app.models.chat_models import SystemPurpose
from app.models.conversation_log_models import Notice
from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.conversation_service import (
    build_playbook_tool_data,
    get_or_create_workflow_conversation,
    log_playbook_run,
)
from shared.py.conversation_wire import ToolDataEntry
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, USER, Runtime

MODULE = "app.services.workflow.conversation_service"


@pytest.mark.unit
class TestGetOrCreateWorkflowConversation:
    async def test_an_existing_workflow_conversation_is_reused(self) -> None:
        repo = MagicMock()
        repo.find_workflow_conversation_id = AsyncMock(return_value="conv-existing")
        create = AsyncMock()

        with (
            patch(f"{MODULE}.conversation_repository", repo),
            patch(f"{MODULE}.create_system_conversation", create),
        ):
            found = await get_or_create_workflow_conversation("wf-1", "user-1", "Digest")

        assert found == "conv-existing"
        repo.find_workflow_conversation_id.assert_awaited_once_with("user-1", "wf-1")
        create.assert_not_awaited()

    async def test_a_first_run_creates_and_binds_its_conversation(self) -> None:
        repo = MagicMock()
        repo.find_workflow_conversation_id = AsyncMock(return_value=None)
        repo.set_workflow_binding = AsyncMock()
        create = AsyncMock(return_value=MagicMock(conversation_id="conv-new"))

        with (
            patch(f"{MODULE}.conversation_repository", repo),
            patch(f"{MODULE}.create_system_conversation", create),
        ):
            created = await get_or_create_workflow_conversation("wf-1", "user-1", "Digest")

        assert created == "conv-new"
        create.assert_awaited_once_with(
            user_id="user-1",
            description="Digest",
            system_purpose=SystemPurpose.WORKFLOW_EXECUTION,
        )
        repo.set_workflow_binding.assert_awaited_once_with(
            "conv-new", user_id="user-1", workflow_id="wf-1", workflow_title="Digest"
        )


@pytest.fixture
def tool_registry() -> None:
    """Register the real tool registry: the replayed calls' cards resolve their categories through it."""
    if not providers.is_initialized("tool_registry"):
        init_tool_registry()


def _card(card: ToolDataEntry) -> tuple[object, ...]:
    data = cast(dict[str, object], card["data"])
    return (card["tool_name"], data["tool_name"], data["inputs"], data["output"])


async def test_a_replay_shows_its_playbook_card_then_every_call_with_its_result(
    tool_registry: None,
) -> None:
    """Regression: a call a subagent made in the recorded run vanished from its replay's cards."""
    playbook = MagicMock(
        description="Send the digest",
        steps=[MagicMock(tool="gmail_send"), MagicMock(tool="slack_post")],
    )
    trace = [
        RecordedCall(
            tool_name="gmail_send", args={"to": "a"}, result_digest="sent", subagent_id="sub-1"
        ),
        RecordedCall(tool_name="slack_post", args={"text": "hi"}, result_digest="posted"),
    ]

    cards = await build_playbook_tool_data(trace, "507f1f77bcf86cd799439011", playbook)

    assert [_card(card) for card in cards] == [
        (
            "tool_calls_data",
            "run_playbook",
            {"description": "Send the digest", "plan": ["gmail_send", "slack_post"]},
            "Replayed 2 frozen step(s): gmail_send; slack_post",
        ),
        ("tool_calls_data", "gmail_send", {"to": "a"}, "sent"),
        ("tool_calls_data", "slack_post", {"text": "hi"}, "posted"),
    ]


async def test_a_replayed_run_is_logged_as_a_notice_naming_its_workflow() -> None:
    runtime = Runtime()
    workflow = MagicMock(id="wf-1", title="Digest")
    with patch(f"{MODULE}.runtime_ports", return_value=runtime.ports):
        await log_playbook_run(CONVERSATION, USER, workflow, "Sent the digest")

    (logged,) = await runtime.log.read_after(CONVERSATION, USER, 0)
    notice = logged.entry
    assert isinstance(notice, Notice)
    assert notice.id.startswith("playbook:")
    assert (notice.text, notice.origin) == (
        "Sent the digest",
        'workflow "Digest" (id wf-1), replayed from its playbook',
    )
