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
7 of 7 on an 8-chunk answer, not just the terminal one. That repetition is why
``PROVIDER_NAME_METADATA_KEY`` joins the idempotent-string set in
``langchain_merge_dicts_model_name_patch``: ``AIMessageChunk.__add__`` merges
``response_metadata`` with ``merge_dicts``, which concatenates equal strings for
any key outside that set, so the merged message would otherwise report
"OpenAIOpenAIOpenAIOpenAIOpenAIOpenAIOpenAI". This is the same failure that
doubled ``model_name``.

Both wrappers delegate to the original and only add the key, so upstream's
behaviour is untouched everywhere ``provider`` is absent (custom base-URL lanes,
OpenAI-compatible gateways that do not send it).

Drop this patch once the SDK declares ``provider`` on both response models and
``ChatOpenRouter`` surfaces it — ``_declare_provider_field`` fails loudly if the
SDK adds the field, so a dependency bump cannot silently leave a stale patch in
place.
"""

from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessageChunk
from langchain_core.outputs import ChatResult
from langchain_openrouter import ChatOpenRouter, chat_models as _chat_models
from openrouter.components.chatresult import ChatResult as SDKChatResult
from openrouter.components.chatstreamchunk import ChatStreamChunk as SDKChatStreamChunk
from pydantic.fields import FieldInfo

from app.constants.llm import PROVIDER_NAME_METADATA_KEY

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
_ORIGINAL_CONVERT_CHUNK = _chat_models._convert_chunk_to_message_chunk


def _declare_provider_field() -> None:
    """Give both SDK response models a real ``provider`` field so pydantic keeps it."""
    for model in _SDK_RESPONSE_MODELS:
        if _WIRE_PROVIDER_KEY in model.model_fields:
            msg = (
                f"{model.__name__} already declares '{_WIRE_PROVIDER_KEY}'; the openrouter "
                "SDK now keeps the provider name itself and this patch is stale."
            )
            raise AttributeError(msg)
        model.model_fields[_WIRE_PROVIDER_KEY] = FieldInfo(
            annotation=_PROVIDER_ANNOTATION, default=None
        )
        model.model_rebuild(force=True)


def _create_chat_result(
    self: ChatOpenRouter, response: SDKChatResult | dict[str, Any]
) -> ChatResult:
    """Stamp the serving upstream's name onto the non-streaming result."""
    # Normalise here rather than dumping twice: the original accepts a dict and
    # only dumps when handed an SDK object.
    if not isinstance(response, dict):
        response = response.model_dump(by_alias=True)
    result = _ORIGINAL_CREATE_CHAT_RESULT(self, response)
    provider = response.get(_WIRE_PROVIDER_KEY)
    if provider:
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
    function both of them route every chunk through, so a single wrapper covers
    the sync and async paths without duplicating either.
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


#: The chat_models module, typed Any because the rebind below writes an
#: attribute typeshed does not declare on a module — the point of a monkeypatch.
_CHAT_MODELS: Any = _chat_models


def apply() -> None:
    """Declare the SDK field, then rebind both metadata builders."""
    _declare_provider_field()
    # setattr through a variable name: monkeypatching a method is exactly what
    # this patch exists to do, and neither mypy's method-assign check nor ruff's
    # B010 has a way to express "this assignment is the point".
    method_name = "_create_chat_result"
    setattr(ChatOpenRouter, method_name, _create_chat_result)
    # `_stream`/`_astream` resolve this by module-global lookup at call time, so
    # rebinding the module attribute reaches both without touching either.
    _CHAT_MODELS._convert_chunk_to_message_chunk = _convert_chunk_to_message_chunk
