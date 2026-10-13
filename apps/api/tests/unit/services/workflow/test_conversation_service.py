"""Unit tests for app.services.workflow.conversation_service."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.user_models import AuthenticatedUser
from app.services.workflow.conversation_service import (
    WORKFLOW_CONVERSATION_MAX_MESSAGES,
    add_workflow_execution_messages,
)

MODULE = "app.services.workflow.conversation_service"


@pytest.mark.unit
class TestAddWorkflowExecutionMessages:
    async def test_messages_are_appended_as_the_workflow_owner_with_the_history_cap(self) -> None:
        messages = [MessageModel(type="bot", response="Workflow finished")]
        update = AsyncMock()

        with patch(f"{MODULE}.update_messages", update):
            await add_workflow_execution_messages("conv-1", messages, "user-1")

        update.assert_awaited_once_with(
            UpdateMessagesRequest(conversation_id="conv-1", messages=messages),
            AuthenticatedUser(user_id="user-1"),
            max_messages=WORKFLOW_CONVERSATION_MAX_MESSAGES,
        )

    async def test_a_failed_append_propagates(self) -> None:
        messages = [MessageModel(type="bot", response="Workflow finished")]

        with (
            patch(f"{MODULE}.update_messages", AsyncMock(side_effect=RuntimeError("mongo down"))),
            pytest.raises(RuntimeError, match="mongo down"),
        ):
            await add_workflow_execution_messages("conv-1", messages, "user-1")
