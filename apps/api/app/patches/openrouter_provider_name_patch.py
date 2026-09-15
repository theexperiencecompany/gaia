"""Keep the name of the upstream that actually served an OpenRouter call.

OpenRouter's body carries provider (e.g. "OpenAI"), naming the real upstream,
but the SDK models drop it (no extra="allow") and ChatOpenRouter never reads
it, always stamping model_provider="openrouter" instead. This patch declares
the field at runtime and stamps it onto
response_metadata[PROVIDER_NAME_METADATA_KEY] — never model_provider, which
is LangChain's own integration-name field for ls_provider/tracing.

Verified live: provider and finish_reason both repeat on every streamed
chunk, which AIMessageChunk.__add__ would concatenate (the same defect that
once doubled model_name into a dead pricing key). _stream/_astream keep only
the first chunk's value; drop this patch once the SDK declares provider
itself — _declare_provider_field fails loudly if it does.
"""

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, BaseMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openrouter import ChatOpenRouter, chat_models as _chat_models
from openrouter.components.chatresult import ChatResult as SDKChatResult
from openrouter.components.chatstreamchunk import ChatStreamChunk as SDKChatStreamChunk
from pydantic.fields import FieldInfo

from app.constants.llm import PROVIDER_NAME_METADATA_KEY

#: Keys that arrive on more than one streamed chunk and would merge into a
#: doubled string. Both are read downstream as exact values (pricing,
#: truncation alarm), so a concatenated value matches nothing at all.
_DEDUPED_RESPONSE_KEYS = (PROVIDER_NAME_METADATA_KEY, "finish_reason")

#: The top-level key OpenRouter names the serving upstream under.
_WIRE_PROVIDER_KEY = "provider"

#: Deliberately loose: pydantic types FieldInfo.annotation as type[Any] | None,
#: but str | None is a types.UnionType at runtime, not a type — narrowing this
#: would mean restating pydantic's signature, not making the code safer.
_PROVIDER_ANNOTATION: Any = str | None

#: The two SDK response models that parse a chat completion — non-streaming and
#: streaming respectively. Both drop unknown keys, so both need the field.
_SDK_RESPONSE_MODELS = (SDKChatResult, SDKChatStreamChunk)

_ORIGINAL_CREATE_CHAT_RESULT = ChatOpenRouter._create_chat_result
#: Typed as pass-throughs: hands them whatever it was handed. run_manager is
#: absent from the wrappers' signatures (langchain-core never passes it);
#: letting it ride in **kwargs forwards it untouched if that ever changes.
_ORIGINAL_STREAM: Callable[..., Iterator[ChatGenerationChunk]] = ChatOpenRouter._stream
_ORIGINAL_ASTREAM: Callable[..., AsyncIterator[ChatGenerationChunk]] = ChatOpenRouter._astream
_ORIGINAL_CONVERT_CHUNK = _chat_models._convert_chunk_to_message_chunk


#: The exact field object injected into both models. Identity is what tells our
#: own injection apart from a field the SDK started declaring itself, which is
#: what makes `apply()` idempotent without silently tolerating a stale patch.
_INJECTED_FIELD = FieldInfo(annotation=_PROVIDER_ANNOTATION, default=None)


def _declare_provider_field() -> None:
    """Give both SDK response models a real provider field so pydantic keeps it."""
    for model in _SDK_RESPONSE_MODELS:
        existing = model.model_fields.get(_WIRE_PROVIDER_KEY)
        if existing is _INJECTED_FIELD:
            continue
        if existing is not None:
            msg = (
                f"{model.__name__} already declares '{_WIRE_PROVIDER_KEY}'; the openrouter "
                "SDK now keeps the provider name itself and this patch is stale."
            )
            raise AttributeError(msg)
        model.model_fields[_WIRE_PROVIDER_KEY] = _INJECTED_FIELD
        model.model_rebuild(force=True)


def _create_chat_result(
    self: ChatOpenRouter, response: SDKChatResult | dict[str, Any]
) -> ChatResult:
    """Stamp the serving upstream's name onto the non-streaming result."""
    result = _ORIGINAL_CREATE_CHAT_RESULT(self, response)
    # Read the name off whichever shape came in rather than dumping the model
    # again — the original already normalises internally, and a second
    # `model_dump` here would just be the same work done twice.
    provider = (
        response.get(_WIRE_PROVIDER_KEY)
        if isinstance(response, dict)
        else getattr(response, _WIRE_PROVIDER_KEY, None)
    )
    if not provider:
        return result
    for generation in result.generations:
        message = generation.message
        if isinstance(message, AIMessage):
            message.response_metadata[PROVIDER_NAME_METADATA_KEY] = provider
    return result


def _convert_chunk_to_message_chunk(
    chunk: Mapping[str, Any], default_class: type[BaseMessageChunk]
) -> BaseMessageChunk:
    """Stamp the serving upstream's name onto one streamed chunk.

    Patched here rather than in _stream/_astream because this is the one
    function both of them route every chunk through, and it is the only place
    with the raw wire chunk the name arrives on. _keep_first_provider_name
    then reduces the repeats to one — see its docstring for why.
    """
    message_chunk = _ORIGINAL_CONVERT_CHUNK(chunk, default_class)
    provider = chunk.get(_WIRE_PROVIDER_KEY)
    if not provider or not isinstance(message_chunk, AIMessageChunk):
        return message_chunk
    return message_chunk.model_copy(
        update={
            "response_metadata": {
                **message_chunk.response_metadata,
                PROVIDER_NAME_METADATA_KEY: provider,
            }
        }
    )


def _keep_first_response_key(chunk: ChatGenerationChunk, key: str, kept_so_far: int) -> int:
    """Drop key from every chunk after the first; return 1 if this one kept it.

    merge_dicts concatenates repeated string keys, so provider/finish_reason
    would double (e.g. "BaiduBaidu", "stopstop") without this. generation_info
    is stripped too because BaseChatModel.stream re-merges it back over the
    message right after this runs, silently undoing a metadata-only delete.
    """
    if not isinstance(chunk.message, AIMessageChunk):
        return 0
    if key not in chunk.message.response_metadata and key not in (chunk.generation_info or {}):
        return 0
    if kept_so_far > 0:
        chunk.message.response_metadata.pop(key, None)
        if chunk.generation_info is not None:
            chunk.generation_info.pop(key, None)
        return 0
    return 1


def _stream(
    self: ChatOpenRouter,
    messages: list[BaseMessage],
    stop: list[str] | None = None,
    **kwargs: object,
) -> Iterator[ChatGenerationChunk]:
    """ChatOpenRouter._stream with every repeated metadata key reduced to one."""
    kept = dict.fromkeys(_DEDUPED_RESPONSE_KEYS, 0)
    for chunk in _ORIGINAL_STREAM(self, messages, stop=stop, **kwargs):
        for key in _DEDUPED_RESPONSE_KEYS:
            kept[key] += _keep_first_response_key(chunk, key, kept[key])
        yield chunk


async def _astream(
    self: ChatOpenRouter,
    messages: list[BaseMessage],
    stop: list[str] | None = None,
    **kwargs: object,
) -> AsyncIterator[ChatGenerationChunk]:
    """ChatOpenRouter._astream with every repeated metadata key reduced to one."""
    kept = dict.fromkeys(_DEDUPED_RESPONSE_KEYS, 0)
    async for chunk in _ORIGINAL_ASTREAM(self, messages, stop=stop, **kwargs):
        for key in _DEDUPED_RESPONSE_KEYS:
            kept[key] += _keep_first_response_key(chunk, key, kept[key])
        yield chunk


#: The chat_models module, typed Any because the rebind below writes an
#: attribute typeshed does not declare on a module — the point of a monkeypatch.
_CHAT_MODELS: Any = _chat_models


def apply() -> None:
    """Declare the SDK field, then rebind both metadata builders."""
    _declare_provider_field()
    # setattr through a variable name: monkeypatching a method is exactly what
    # this patch exists to do, and neither mypy's method-assign check nor ruff's
    # B010 has a way to express "this assignment is the point".
    replacements: dict[str, object] = {
        "_create_chat_result": _create_chat_result,
        "_stream": _stream,
        "_astream": _astream,
    }
    for method_name, replacement in replacements.items():
        setattr(ChatOpenRouter, method_name, replacement)
    # `_stream`/`_astream` resolve this by module-global lookup at call time, so
    # rebinding the module attribute reaches both without touching either.
    _CHAT_MODELS._convert_chunk_to_message_chunk = _convert_chunk_to_message_chunk
