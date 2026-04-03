"""
Service tests: call real construct_langchain_messages().

Mock only: get_memory_message (needs Mem0), get_platform_context_message (needs integrations).
Real: create_system_message, format_files_list, format_reply_context,
format_tool_selection_message, message list construction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.core.messages import construct_langchain_messages


@pytest.mark.service
class TestConstructMessagesReal:
    """Call real construct_langchain_messages with minimal mocking."""

    async def test_basic_message_produces_system_and_human(self):
        """A simple message must produce at least a SystemMessage and HumanMessage."""
        with (
            patch(
                "app.agents.core.messages.get_memory_message",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.messages.get_platform_context_message",
                new=MagicMock(return_value=None),
            ),
        ):
            messages = await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hello"}],
                user_id="test-user",
                user_name="Test",
                query="Hello",
            )

        assert len(messages) >= 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[-1], HumanMessage)
        assert "Hello" in messages[-1].content

    async def test_tool_selection_adds_instruction(self):
        """selected_tool must add a tool selection instruction."""
        with (
            patch(
                "app.agents.core.messages.get_memory_message",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.messages.get_platform_context_message",
                new=MagicMock(return_value=None),
            ),
        ):
            messages = await construct_langchain_messages(
                messages=[{"role": "user", "content": "Search for cats"}],
                user_id="test-user",
                user_name="Test",
                query="Search for cats",
                selected_tool="web_search",
            )

        all_content = " ".join(str(m.content) for m in messages)
        assert "web_search" in all_content

    async def test_system_message_is_first(self):
        """First message must always be a SystemMessage."""
        with (
            patch(
                "app.agents.core.messages.get_memory_message",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.messages.get_platform_context_message",
                new=MagicMock(return_value=None),
            ),
        ):
            messages = await construct_langchain_messages(
                messages=[{"role": "user", "content": "What can you do?"}],
                user_id="test-user",
                query="What can you do?",
            )

        assert len(messages) >= 1
        assert isinstance(messages[0], SystemMessage)
