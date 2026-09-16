"""Unit tests for chat_utils description generation and one-shot prompting."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.models.message_models import MessageDict
from app.utils.chat_utils import (
    _generate_description_from_message,
    do_prompt_no_stream,
    generate_and_update_description,
)


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


class TestDescriptionAttribution:
    """The detached title task must bill to its user and join its turn's
    trace — otherwise every new conversation's title is unattributed spend
    on an orphan trace."""

    @patch("app.agents.llm.chatbot.get_helper_llm")
    @patch("app.agents.llm.chatbot.ainvoke_llm", new_callable=AsyncMock)
    @patch("app.utils.chat_utils.trace_id_for_message", return_value="trace-9")
    async def test_threads_user_session_and_trace_into_config(
        self, mock_trace: MagicMock, mock_ainvoke: AsyncMock, mock_get_default: MagicMock
    ) -> None:
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.return_value = AIMessage(content='"Weekly planning"')
        last_message: MessageDict = {"role": "user", "content": "plan my week"}

        await _generate_description_from_message(
            last_message,
            selectedTool=None,
            selectedWorkflow=None,
            user_id="u-1",
            conversation_id="conv-1",
            bot_message_id="bot-7",
        )

        config = mock_ainvoke.call_args.kwargs["config"]
        assert config["configurable"]["user_id"] == "u-1"
        assert config["metadata"]["langfuse_session_id"] == "conv-1"
        assert config["metadata"]["langfuse_trace_id"] == "trace-9"
        mock_trace.assert_called_once_with("bot-7")
        sent = mock_ainvoke.call_args.args[1]
        assert "plan my week" in sent[0].content

    @patch("app.agents.llm.chatbot.get_helper_llm")
    @patch("app.agents.llm.chatbot.ainvoke_llm", new_callable=AsyncMock)
    async def test_absent_ids_leave_no_trace_key(
        self, mock_ainvoke: AsyncMock, mock_get_default: MagicMock
    ) -> None:
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.return_value = AIMessage(content='"Weekly planning"')
        last_message: MessageDict = {"role": "user", "content": "plan my week"}

        await _generate_description_from_message(
            last_message, selectedTool=None, selectedWorkflow=None
        )

        assert mock_ainvoke.call_args.kwargs["config"] is None

    @patch("app.utils.chat_utils.update_conversation_description", new_callable=AsyncMock)
    @patch("app.utils.chat_utils._generate_description_from_message", new_callable=AsyncMock)
    async def test_forwards_identity_to_generation(
        self, mock_generate: AsyncMock, mock_persist: AsyncMock
    ) -> None:
        mock_generate.return_value = "Weekly planning"
        user: dict = {"user_id": "u-1"}

        await generate_and_update_description(
            "conv-1",
            {"role": "user", "content": "hi"},
            user,
            None,
            None,
            "bot-7",
        )

        assert mock_generate.call_args.kwargs["user_id"] == "u-1"
        assert mock_generate.call_args.kwargs["conversation_id"] == "conv-1"
        assert mock_generate.call_args.kwargs["bot_message_id"] == "bot-7"

    @patch("app.utils.chat_utils.update_conversation_description", new_callable=AsyncMock)
    @patch("app.utils.chat_utils._generate_description_from_message", new_callable=AsyncMock)
    async def test_empty_user_forwards_empty_string(
        self, mock_generate: AsyncMock, mock_persist: AsyncMock
    ) -> None:
        mock_generate.return_value = "Weekly planning"

        await generate_and_update_description(
            "conv-1",
            {"role": "user", "content": "hi"},
            {},
            None,
            None,
            "bot-7",
        )

        assert mock_generate.call_args.kwargs["user_id"] == ""
