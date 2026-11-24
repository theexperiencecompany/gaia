"""Workers AI's chat model: ChatOpenAI over its OpenAI-compatible API, with every way it differs from OpenAI handled here."""

from collections.abc import AsyncIterator, Iterator

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, JsonValue

from app.agents.llm.schema_caps import without_size_caps
from app.agents.llm.stream_metadata import keep_first_response_key

_FINISH_REASON = "finish_reason"
_TOOLS = "tools"
#: Request fields that only mean something next to a tool list.
_TOOL_ONLY_FIELDS = (_TOOLS, "tool_choice", "parallel_tool_calls")


class _FunctionSpec(BaseModel):
    """The function block of an OpenAI tool spec; every other key rides along."""

    model_config = ConfigDict(extra="allow")

    parameters: JsonValue = None


class _ToolSpec(BaseModel):
    """An OpenAI tool spec as it sits in a request; every other key rides along."""

    model_config = ConfigDict(extra="allow")

    function: _FunctionSpec | None = None


def _without_caps(tool: JsonValue) -> JsonValue:
    """Return an OpenAI tool spec with the size caps taken out of its arguments' schema."""
    spec = _ToolSpec.model_validate(tool)
    if spec.function is None or "parameters" not in spec.function.model_fields_set:
        return tool
    spec.function.parameters = without_size_caps(spec.function.parameters)
    return spec.model_dump(exclude_unset=True)


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
    """ChatOpenAI for Workers AI: the one place its differences from OpenAI are handled.

    A stream carries usage on every chunk and the total on the last, so merged chunks
    billed twice (live: 66/56 for a 33/28 call), and its finish_reason arrives three
    times: only the last usage frame and the first finish_reason leave. A strict tool
    call is cut at maxLength/maxItems (a forced one once too), so no tool carries a size cap.
    An empty tools array is a 400, so it is left off the request.
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: object,
    ) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = super()._get_request_payload(input_, stop=stop, **kwargs)
        tools = payload.get(_TOOLS)
        if isinstance(tools, list) and tools:
            payload[_TOOLS] = [_without_caps(tool) for tool in tools]
        elif _TOOLS in payload:
            for field in _TOOL_ONLY_FIELDS:
                payload.pop(field, None)
        return payload

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> Iterator[ChatGenerationChunk]:
        reducer = _StreamReducer()
        # Equivalent under mutation: langchain-core never passes run_manager here, it fires callbacks.
        for chunk in super()._stream(  # pragma: no mutate
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
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
        # Equivalent under mutation: langchain-core never passes run_manager here, it fires callbacks.
        async for chunk in super()._astream(  # pragma: no mutate
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield reducer.reduce(chunk)
        if (closing := reducer.closing_usage()) is not None:
            yield closing
