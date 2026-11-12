"""Unit tests for app.services.workflow.conversation_service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat_models import SystemPurpose
from app.services.workflow.conversation_service import (
    get_or_create_workflow_conversation,
)

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
