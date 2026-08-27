"""Unit tests for chat_utils description generation and one-shot prompting."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.models.message_models import MessageDict
from app.utils.chat_utils import _generate_description_from_message, do_prompt_no_stream


class TestGenerateDescriptionFromMessage:
    @pytest.mark.regression
    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.ainvoke_llm", new_callable=AsyncMock)
    async def test_falls_back_to_new_chat_when_llm_call_fails(
        self, mock_ainvoke: AsyncMock, mock_log: object
    ) -> None:
        # An operational LLM failure (provider outage, out-of-credits, ...) must
        # never surface as the conversation's title — chatbot() used to swallow
        # this and hand back a fake success message that got persisted verbatim.
        mock_ainvoke.side_effect = ConnectionError("provider down")
        last_message: MessageDict = {"role": "user", "content": "plan my week"}

        description = await _generate_description_from_message(
            last_message, selectedTool=None, selectedWorkflow=None
        )

        assert description == "New Chat"

    @patch("app.agents.llm.chatbot.get_helper_llm")
    @patch("app.agents.llm.chatbot.ainvoke_llm", new_callable=AsyncMock)
    async def test_uses_llm_response_on_success(
        self, mock_ainvoke: AsyncMock, mock_get_default: MagicMock
    ) -> None:
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.return_value = AIMessage(content='"Weekly planning"')
        last_message: MessageDict = {"role": "user", "content": "plan my week"}

        description = await _generate_description_from_message(
            last_message, selectedTool=None, selectedWorkflow=None
        )

        assert description == "Weekly planning"


class TestDoPromptNoStream:
    @patch("app.agents.llm.chatbot.get_helper_llm")
    @patch("app.agents.llm.chatbot.ainvoke_llm", new_callable=AsyncMock)
    async def test_propagates_operational_llm_failures(
        self, mock_ainvoke: AsyncMock, mock_get_default: MagicMock
    ) -> None:
        # Callers (e.g. image prompt refinement) must see the failure, not a
        # fabricated "successful" response they'd silently treat as real output.
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.side_effect = ConnectionError("provider down")

        with pytest.raises(ConnectionError, match="provider down"):
            await do_prompt_no_stream(prompt="refine this")
