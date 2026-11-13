"""Workers AI's chat model: ChatOpenAI over its OpenAI-compatible API, its stream reduced to OpenAI's."""

from collections.abc import AsyncIterator, Iterator

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

from app.agents.llm.stream_metadata import keep_first_response_key

_FINISH_REASON = "finish_reason"


class _StreamReducer:
    """One stream's state: how many finish_reasons were kept, and the latest usage frame."""

    def __init__(self) -> None:
        self._finish_reasons_kept = 0
        self._usage: UsageMetadata | None = None

    def reduce(self, chunk: ChatGenerationChunk) -> ChatGenerationChunk:
        """Hold back chunk's usage and drop any finish_reason after the first."""
        self._finish_reasons_kept += keep_first_response_key(
            chunk, _FINISH_REASON, self._finish_reasons_kept
        )
        message = chunk.message
        if isinstance(message, AIMessageChunk) and message.usage_metadata is not None:
            self._usage = message.usage_metadata
            message.usage_metadata = None
        return chunk

    def closing_usage(self) -> ChatGenerationChunk | None:
        """Return the last usage frame as a usage-only chunk, the way OpenAI closes a stream."""
        if self._usage is None:
            return None
        return ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=self._usage))


class ChatWorkersAI(ChatOpenAI):
    """ChatOpenAI for Workers AI, whose stream repeats what OpenAI's states once.

    Every chunk carries its own usage and the last one the call's total, so merged
    chunks billed twice (live: 66/56 for a 33/28 call); the closing finish_reason
    arrives three times. Only the last usage frame and the first finish_reason leave.
    """

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> Iterator[ChatGenerationChunk]:
        reducer = _StreamReducer()
        for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield reducer.reduce(chunk)
        if (closing := reducer.closing_usage()) is not None:
            yield closing

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        reducer = _StreamReducer()
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield reducer.reduce(chunk)
        if (closing := reducer.closing_usage()) is not None:
            yield closing
