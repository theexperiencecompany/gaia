"""Keep the name of the upstream that actually served an OpenRouter call.

OpenRouter is an aggregator: every chat-completion body it returns carries a
top-level ``provider`` field naming the real upstream that served the request
("OpenAI", "Baidu", "StreamLake", ...). That name is the only handle on *which*
upstream answered, and nothing downstream can currently see it, for two
independent reasons — both of which this patch closes.

1. **The ``openrouter`` SDK throws it away.** ``ChatResult`` and
   ``ChatStreamChunk`` (both Speakeasy-generated) declare no ``provider`` field,
   and their pydantic config does not set ``extra="allow"``, so pydantic's
   default ``extra="ignore"`` drops the key during validation. By the time
   ``ChatOpenRouter`` calls ``model_dump(by_alias=True)`` the name is already
   gone, so no amount of patching langchain alone can recover it. Declaring the
   field at runtime is what makes it survive — note that ``extra="allow"`` would
   NOT be enough, because both models' hand-written ``serialize_model`` wrap
   serializer rebuilds its output from ``model_fields`` only and discards
   anything extra.

2. **``ChatOpenRouter`` never reads it.** ``_create_chat_result`` lifts
   ``model``/``system_fingerprint``/``cost`` off the payload and
   ``_convert_chunk_to_message_chunk`` builds the streaming chunk's
   ``response_metadata``, but neither looks at ``provider``. Both stamp
   ``model_provider`` as the literal ``"openrouter"`` — the aggregator's own
   name, which is exactly the value that is not useful.

The upstream name lands in ``response_metadata[PROVIDER_NAME_METADATA_KEY]``
rather than in ``model_provider``: ``model_provider`` is LangChain's own field
naming the *integration* that produced the message, it is what
``ls_provider``/tracing key off, and "openrouter" is the honest answer there.
Overwriting it would make the two meanings collide.

Verified against live OpenRouter traffic (openai/gpt-4o-mini, 2026-08): the
non-streaming body carries ``provider``, and so does *every* streamed chunk —
7 of 7 on an 8-chunk answer. Those repeats would merge into
"OpenAIOpenAIOpenAI...", because ``AIMessageChunk.__add__`` merges
``response_metadata`` with ``merge_dicts``, which concatenates equal strings for
any key outside its small idempotent set — the same failure that once doubled
``model_name`` into a pricing key matching nothing. So ``_stream``/``_astream``
are wrapped to keep the name on the first chunk that carries it and strip it
from the rest.

Stamping only the ``finish_reason`` chunk instead would look tidier and is
wrong: that slot is not unique either. The same live 8-chunk answer carried TWO
finish events — one closing the reasoning block, one closing the content — and
doubled the name just as thoroughly. "First one wins" is the only rule that
holds however many chunks carry it, and it keeps the fix in this module rather
than adding a key to another patch's idempotent set.

Both wrappers delegate to the original and only add the key, so upstream's
behaviour is untouched everywhere ``provider`` is absent (custom base-URL lanes,
OpenAI-compatible gateways that do not send it).

Drop this patch once the SDK declares ``provider`` on both response models and
``ChatOpenRouter`` surfaces it — ``_declare_provider_field`` fails loudly if the
SDK adds the field, so a dependency bump cannot silently leave a stale patch in
place.
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

#: Response-metadata keys that arrive on more than one streamed chunk and would
#: otherwise merge into a doubled string. Both are read downstream as exact
#: values — one prices a call, the other alarms on truncation — so a
#: concatenated value matches nothing rather than being merely untidy.
_DEDUPED_RESPONSE_KEYS = (PROVIDER_NAME_METADATA_KEY, "finish_reason")

#: The top-level key OpenRouter names the serving upstream under.
_WIRE_PROVIDER_KEY = "provider"

#: The annotation the injected field carries. Deliberately loose: pydantic types
#: ``FieldInfo.annotation`` as ``type[Any] | None``, but its runtime contract
#: accepts any annotation object — ``str | None`` is a ``types.UnionType``, not a
#: ``type``, so the honest value does not fit the declared parameter. Narrowing
#: this would mean restating pydantic's signature, not making the code safer.
_PROVIDER_ANNOTATION: Any = str | None

#: The two SDK response models that parse a chat completion — non-streaming and
#: streaming respectively. Both drop unknown keys, so both need the field.
_SDK_RESPONSE_MODELS = (SDKChatResult, SDKChatStreamChunk)

_ORIGINAL_CREATE_CHAT_RESULT = ChatOpenRouter._create_chat_result
#: Typed as the pass-throughs this module treats them as — it hands them whatever
#: it was handed. `run_manager` is deliberately absent from the wrappers'
#: signatures: langchain-core never passes it, and letting it ride in `**kwargs`
#: forwards it untouched if that ever changes, rather than silently dropping it.
_ORIGINAL_STREAM: Callable[..., Iterator[ChatGenerationChunk]] = ChatOpenRouter._stream
_ORIGINAL_ASTREAM: Callable[..., AsyncIterator[ChatGenerationChunk]] = ChatOpenRouter._astream
_ORIGINAL_CONVERT_CHUNK = _chat_models._convert_chunk_to_message_chunk


#: The exact field object injected into both models. Identity is what tells our
#: own injection apart from a field the SDK started declaring itself, which is
#: what makes `apply()` idempotent without silently tolerating a stale patch.
_INJECTED_FIELD = FieldInfo(annotation=_PROVIDER_ANNOTATION, default=None)


def _declare_provider_field() -> None:
    """Give both SDK response models a real ``provider`` field so pydantic keeps it."""
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

    Patched here rather than in ``_stream``/``_astream`` because this is the one
    function both of them route every chunk through, and it is the only place
    with the raw wire chunk the name arrives on. ``_keep_first_provider_name``
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
    """Drop ``key`` from every chunk after the first; return 1 if this one kept it.

    A running count rather than a bool so the caller's accumulator has to start
    at a real number — the arithmetic is what makes a wrong initial value fail
    loudly instead of silently behaving like "not seen yet".

    ``AIMessageChunk.__add__`` merges ``response_metadata`` with ``merge_dicts``,
    which CONCATENATES equal strings for any key outside its small idempotent
    set. So any repeated key merges into a doubled value, and both keys this
    module de-duplicates arrive more than once:

    - ``provider`` is repeated by OpenRouter on every chunk, merging into
      "BaiduBaiduBaidu".
    - ``finish_reason`` arrives once per finish event, and a streamed answer has
      more than one — verified live, an 8-chunk answer carried TWO (one closing
      the reasoning block, one closing the content). Observed in the ledger as
      ``"stopstop"`` and ``"tool_callstool_calls"``.

    Both are the same defect that once doubled ``model_name`` into a pricing key
    matching nothing. A doubled ``finish_reason`` is worse than useless: a query
    for ``length`` can never match, so the truncation alarm the field exists for
    can never fire.

    "First one wins" is the only rule that holds however many chunks carry a
    key. It is a real tradeoff for ``finish_reason``: a stream whose two finish
    events disagree reports the earlier one. Every doubled value observed live
    was an identical pair (``"stopstop"``, ``"tool_callstool_calls"``), and a
    single wrong-but-valid reason is still queryable, whereas a concatenation
    matches nothing at all.

    ``generation_info`` is stripped alongside ``response_metadata`` because
    ``BaseChatModel.stream`` re-merges it back over the message
    (``_gen_info_and_msg_metadata``, chat_models.py:781/914) AFTER this runs —
    deleting from the metadata alone is silently undone one frame later, which
    is exactly how the doubled values reached the ledger.
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
    """``ChatOpenRouter._stream`` with every repeated metadata key reduced to one."""
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
    """``ChatOpenRouter._astream`` with every repeated metadata key reduced to one."""
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
