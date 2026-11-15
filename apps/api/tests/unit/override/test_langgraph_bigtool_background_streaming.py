"""A run no one watches live makes its model calls unstreamed; a live one keeps streaming."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.utils import ConfigurableField
import pytest

from app.constants.llm import STREAMING_FIELD_ID
from app.override.langgraph_bigtool.agent_config import ToolRetrievalConfig
from app.override.langgraph_bigtool.create_agent import create_agent
from app.services.llm_metering import extract_message_usage

_USAGE = UsageMetadata(input_tokens=11, output_tokens=3, total_tokens=14)
_PIECES = ("one ", "two ", "three")


class _TwoWayChat(BaseChatModel):
    """Answers the same text and usage whether it streams or not."""

    streaming: bool = True

    @property
    def _llm_type(self) -> str:
        return "two-way-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = AIMessage(content="".join(_PIECES), usage_metadata=_USAGE)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for piece in _PIECES:
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=_USAGE))

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


class _TokenCounter(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.tokens = 0

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        self.tokens += 1


async def _run_model_node(execution_mode: str) -> tuple[AIMessage, int]:
    """Run the graph's model node once and return its reply and how many tokens streamed."""
    llm = _TwoWayChat(streaming=True).configurable_fields(
        streaming=ConfigurableField(id=STREAMING_FIELD_ID)
    )
    builder = create_agent(llm, {}, tools_config=ToolRetrievalConfig(disable_retrieve_tools=True))
    node = builder.nodes["agent"].runnable
    counter = _TokenCounter()
    config: RunnableConfig = {
        "configurable": {"execution_mode": execution_mode},
        "callbacks": [counter],
        "recursion_limit": 25,
    }
    state = {
        "messages": [HumanMessage(content="go")],
        "selected_tool_ids": [],
        "todos": [],
        "intent": None,
        "integration_usernames": {},
        "remaining_steps": 25,
    }
    result = await node.afunc(state, config, store=MagicMock())  # type: ignore[union-attr]  # the node is a RunnableCallable
    reply = result["messages"][-1]
    assert isinstance(reply, AIMessage)
    return reply, counter.tokens


@pytest.mark.asyncio
async def test_a_background_runs_model_call_is_not_streamed() -> None:
    _, tokens = await _run_model_node("background")

    assert tokens == 0


@pytest.mark.asyncio
async def test_an_interactive_runs_model_call_streams() -> None:
    _, tokens = await _run_model_node("interactive")

    assert tokens > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_mode", ["background", "interactive"])
async def test_the_reply_carries_the_usage_accounting_reads_either_way(
    execution_mode: str,
) -> None:
    reply, _ = await _run_model_node(execution_mode)

    assert reply.content == "".join(_PIECES)
    assert extract_message_usage(reply)["input_tokens"] == _USAGE["input_tokens"]
    assert extract_message_usage(reply)["output_tokens"] == _USAGE["output_tokens"]
