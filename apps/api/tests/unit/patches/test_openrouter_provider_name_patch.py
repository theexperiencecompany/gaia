"""Tests for the OpenRouter provider-name patch.

OpenRouter returns the name of the upstream that actually served a call in a
top-level ``provider`` field. Two layers used to lose it: the ``openrouter``
SDK's response models drop the unknown key during pydantic validation, and
``ChatOpenRouter`` never reads it and reports ``model_provider="openrouter"`` —
the aggregator's own name. The patch restores the real name into
``response_metadata[PROVIDER_NAME_METADATA_KEY]`` on both the streaming and
non-streaming paths.

The streaming tests drive the real ``ChatOpenRouter`` against a loopback SSE
endpoint, so they exercise the SDK's parsing (where the drop happened) and
``AIMessageChunk.__add__``'s merge (where the repeated value would concatenate)
rather than just the wrapper's own arithmetic.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from openrouter.components.chatresult import ChatResult as SDKChatResult
from openrouter.components.chatstreamchunk import ChatStreamChunk as SDKChatStreamChunk
from openrouter.types import BaseModel as SDKBaseModel
from pydantic import SecretStr
from pydantic.fields import FieldInfo
import pytest

from app.constants.llm import PROVIDER_NAME_METADATA_KEY

# Importing the package applies every patch, including this one and the
# merge-idempotency patch the streamed value depends on.
from app.patches import openrouter_provider_name_patch as _patch

# Reusing the sibling suite's loopback wire rather than adding a third copy of
# it; `tests/unit/helpers/` already cross-imports it the same way.
from .test_openrouter_cumulative_usage_patch import _ScriptedWire

MODEL = "openai/gpt-4o-mini"
UPSTREAM = "StreamLake"


def _sse(chunk: dict[str, Any]) -> str:
    return f"data: {json.dumps(chunk)}\n\n"


def _chunk(content: str, *, provider: str | None, finish: str | None = None) -> dict[str, Any]:
    chunk: dict[str, Any] = {
        "id": "gen-1",
        "created": 1,
        "model": MODEL,
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
    }
    if provider is not None:
        chunk["provider"] = provider
    return chunk


def _turn(*, provider: str | None) -> list[str]:
    """A three-chunk answer, with `provider` repeated on every chunk as the wire does."""
    return [
        _sse(_chunk("he", provider=provider)),
        _sse(_chunk("ll", provider=provider)),
        _sse(_chunk("o", provider=provider, finish="stop")),
    ]


def _client(base_url: str) -> Any:
    from langchain_openrouter import ChatOpenRouter

    return ChatOpenRouter(model=MODEL, api_key=SecretStr("k"), base_url=base_url, streaming=True)


def _sdk_result(*, provider: str | None) -> SDKChatResult:
    payload: dict[str, Any] = {
        "id": "gen-1",
        "created": 1,
        "model": MODEL,
        "object": "chat.completion",
        "system_fingerprint": "fp",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hello"},
            }
        ],
    }
    if provider is not None:
        payload["provider"] = provider
    return SDKChatResult.model_validate(payload)


class TestSDKKeepsTheField:
    """The first of the two losses: pydantic dropping an undeclared key."""

    def test_non_streaming_model_keeps_provider_through_model_dump(self) -> None:
        dumped = _sdk_result(provider=UPSTREAM).model_dump(by_alias=True)
        assert dumped["provider"] == UPSTREAM

    def test_streaming_model_keeps_provider_through_model_dump(self) -> None:
        chunk = SDKChatStreamChunk.model_validate(_chunk("hi", provider=UPSTREAM, finish="stop"))
        assert chunk.model_dump(by_alias=True)["provider"] == UPSTREAM

    @pytest.mark.parametrize("model", [SDKChatResult, SDKChatStreamChunk])
    def test_field_is_declared_and_optional(self, model: type) -> None:
        """Absent on the wire must stay absent, not become a required field."""
        field = model.model_fields["provider"]
        assert field.default is None


def _throwaway_model(name: str) -> type[SDKBaseModel]:
    """A disposable stand-in for an SDK response model.

    The declaration logic is exercised against these rather than against the real
    `ChatResult`/`ChatStreamChunk`, which the patch has already modified at import
    and whose rebuilt validators would outlive any monkeypatch of `model_fields`.
    """
    return type(name, (SDKBaseModel,), {"__annotations__": {"model": str}})


class TestFieldDeclaration:
    """`_declare_provider_field`, driven over disposable models."""

    def test_the_field_is_added_and_actually_takes_effect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Declared *and* rebuilt — without the rebuild the validator still drops it."""
        model = _throwaway_model("Fresh")
        monkeypatch.setattr(_patch, "_SDK_RESPONSE_MODELS", (model,))

        _patch._declare_provider_field()

        parsed = model.model_validate({"model": "m", "provider": "Baidu"})
        assert parsed.model_dump()["provider"] == "Baidu"

    def test_every_model_in_the_tuple_is_declared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Already-patched models must not stop the loop before later ones."""
        done = _throwaway_model("AlreadyOurs")
        done.model_fields["provider"] = _patch._INJECTED_FIELD
        pending = _throwaway_model("Pending")
        monkeypatch.setattr(_patch, "_SDK_RESPONSE_MODELS", (done, pending))

        _patch._declare_provider_field()

        assert pending.model_fields["provider"] is _patch._INJECTED_FIELD

    def test_a_field_the_sdk_declares_itself_fails_loudly_as_a_stale_patch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dependency bump that adds `provider` upstream must not pass silently."""
        model = _throwaway_model("ChatResult")
        model.model_fields["provider"] = FieldInfo(annotation=str, default=None)
        monkeypatch.setattr(_patch, "_SDK_RESPONSE_MODELS", (model,))

        with pytest.raises(AttributeError) as excinfo:
            _patch._declare_provider_field()
        # The exact message: it has to name the model and the key to be
        # actionable on a bump, and say plainly what the reader must do.
        assert str(excinfo.value) == (
            "ChatResult already declares 'provider'; the openrouter SDK now keeps "
            "the provider name itself and this patch is stale."
        )


class TestWiring:
    """apply() must rebind the two specific seams, on the right objects.

    These re-run `apply()` rather than only inspecting the state left by import,
    so the wiring is actually exercised: a rebind pointed at the wrong attribute
    or the wrong function would otherwise never be executed by the suite.
    """

    @pytest.fixture(autouse=True)
    def _unbind_then_restore(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Put both seams back to the library's originals for the duration."""
        from langchain_openrouter import ChatOpenRouter, chat_models

        monkeypatch.setattr(
            ChatOpenRouter, "_create_chat_result", _patch._ORIGINAL_CREATE_CHAT_RESULT
        )
        monkeypatch.setattr(
            chat_models, "_convert_chunk_to_message_chunk", _patch._ORIGINAL_CONVERT_CHUNK
        )
        monkeypatch.setattr(ChatOpenRouter, "_stream", _patch._ORIGINAL_STREAM)
        monkeypatch.setattr(ChatOpenRouter, "_astream", _patch._ORIGINAL_ASTREAM)

    def test_apply_rebinds_the_non_streaming_seam(self) -> None:
        from langchain_openrouter import ChatOpenRouter

        assert ChatOpenRouter._create_chat_result is _patch._ORIGINAL_CREATE_CHAT_RESULT
        _patch.apply()
        assert ChatOpenRouter._create_chat_result is _patch._create_chat_result

    def test_apply_rebinds_the_streaming_seam(self) -> None:
        from langchain_openrouter import chat_models

        assert chat_models._convert_chunk_to_message_chunk is _patch._ORIGINAL_CONVERT_CHUNK
        _patch.apply()
        assert chat_models._convert_chunk_to_message_chunk is _patch._convert_chunk_to_message_chunk

    def test_apply_is_idempotent(self) -> None:
        """It runs once at import and again on every reload; a second call must
        not trip the stale-patch guard on the field it declared itself."""
        _patch.apply()
        _patch.apply()
        assert SDKChatResult.model_fields["provider"] is _patch._INJECTED_FIELD
        assert SDKChatStreamChunk.model_fields["provider"] is _patch._INJECTED_FIELD

    def test_apply_rebinds_both_streaming_seams(self) -> None:
        from langchain_openrouter import ChatOpenRouter

        assert ChatOpenRouter._stream is _patch._ORIGINAL_STREAM
        assert ChatOpenRouter._astream is _patch._ORIGINAL_ASTREAM
        _patch.apply()
        assert ChatOpenRouter._stream is _patch._stream
        assert ChatOpenRouter._astream is _patch._astream

    def test_wrappers_delegate_to_the_captured_originals(self) -> None:
        """The originals must be the library's, not our own wrappers — a
        self-referential capture would recurse forever on the first call."""
        assert _patch._ORIGINAL_CREATE_CHAT_RESULT is not _patch._create_chat_result
        assert _patch._ORIGINAL_CONVERT_CHUNK is not _patch._convert_chunk_to_message_chunk


class _ResultWithoutProvider(SDKBaseModel):
    """A chat-completion response model from before `provider` was declared."""

    choices: list[dict[str, Any]]
    created: int
    id: str
    model: str
    object: str
    system_fingerprint: str | None = None


class TestNonStreaming:
    def test_provider_name_reaches_response_metadata(self) -> None:
        llm = _client("http://127.0.0.1:1/v1")
        result = llm._create_chat_result(_sdk_result(provider="Baidu"))
        assert (
            result.generations[0].message.response_metadata[PROVIDER_NAME_METADATA_KEY] == "Baidu"
        )

    def test_model_provider_still_names_the_integration(self) -> None:
        """The upstream's name is added beside model_provider, never over it."""
        llm = _client("http://127.0.0.1:1/v1")
        result = llm._create_chat_result(_sdk_result(provider="Baidu"))
        assert result.generations[0].message.response_metadata["model_provider"] == "openrouter"

    def test_absent_provider_leaves_the_key_off(self) -> None:
        llm = _client("http://127.0.0.1:1/v1")
        result = llm._create_chat_result(_sdk_result(provider=None))
        assert PROVIDER_NAME_METADATA_KEY not in result.generations[0].message.response_metadata

    def test_an_already_dumped_payload_works_too(self) -> None:
        """`_create_chat_result` accepts a plain dict as well as an SDK object."""
        llm = _client("http://127.0.0.1:1/v1")
        payload = _sdk_result(provider="Baidu").model_dump(by_alias=True)
        result = llm._create_chat_result(payload)
        assert (
            result.generations[0].message.response_metadata[PROVIDER_NAME_METADATA_KEY] == "Baidu"
        )

    def test_the_model_name_falls_back_to_the_client(self) -> None:
        """A payload with no `model` makes the original read `self.model_name` —
        so the wrapper has to forward the real instance, not drop it."""
        llm = _client("http://127.0.0.1:1/v1")
        payload = _sdk_result(provider="Baidu").model_dump(by_alias=True)
        del payload["model"]

        result = llm._create_chat_result(payload)

        assert result.llm_output is not None
        assert result.llm_output["model_name"] == MODEL

    def test_an_object_without_the_field_is_treated_as_absent(self) -> None:
        """A response model that never declared `provider` must read as "no name",
        not raise."""
        llm = _client("http://127.0.0.1:1/v1")
        payload = _sdk_result(provider=None).model_dump(by_alias=True)

        result = llm._create_chat_result(_ResultWithoutProvider(**payload))

        assert PROVIDER_NAME_METADATA_KEY not in result.generations[0].message.response_metadata

    def test_a_non_ai_message_is_left_alone(self) -> None:
        """Only an AI message gets the stamp — response_metadata is its field."""
        llm = _client("http://127.0.0.1:1/v1")
        payload = _sdk_result(provider="Baidu").model_dump(by_alias=True)
        payload["choices"][0]["message"]["role"] = "system"

        result = llm._create_chat_result(payload)

        message = result.generations[0].message
        assert not isinstance(message, AIMessage)
        assert PROVIDER_NAME_METADATA_KEY not in message.response_metadata


def _gen_chunk(message: Any) -> ChatGenerationChunk:
    return ChatGenerationChunk(message=message)


class TestKeepFirstResponseKey:
    """The per-stream de-duplicator, exercised directly.

    Its branches are unreachable through a scripted wire — every chunk a real
    stream yields is an `AIMessageChunk` — so the contract is pinned here.
    """

    def test_the_first_stamped_chunk_keeps_the_name_and_counts(self) -> None:
        chunk = _gen_chunk(
            AIMessageChunk(content="", response_metadata={PROVIDER_NAME_METADATA_KEY: UPSTREAM})
        )
        assert _patch._keep_first_response_key(chunk, PROVIDER_NAME_METADATA_KEY, 0) == 1
        assert chunk.message.response_metadata[PROVIDER_NAME_METADATA_KEY] == UPSTREAM

    def test_a_later_stamped_chunk_is_stripped_and_does_not_count(self) -> None:
        chunk = _gen_chunk(
            AIMessageChunk(content="", response_metadata={PROVIDER_NAME_METADATA_KEY: UPSTREAM})
        )
        assert _patch._keep_first_response_key(chunk, PROVIDER_NAME_METADATA_KEY, 1) == 0
        assert PROVIDER_NAME_METADATA_KEY not in chunk.message.response_metadata

    def test_an_unstamped_chunk_does_not_count(self) -> None:
        """Counting it would strip the name off the first chunk that does carry it."""
        chunk = _gen_chunk(AIMessageChunk(content="hi"))
        assert _patch._keep_first_response_key(chunk, PROVIDER_NAME_METADATA_KEY, 0) == 0

    def test_a_non_ai_chunk_does_not_count(self) -> None:
        from langchain_core.messages import ToolMessageChunk

        chunk = _gen_chunk(ToolMessageChunk(content="x", tool_call_id="t1"))
        assert _patch._keep_first_response_key(chunk, PROVIDER_NAME_METADATA_KEY, 0) == 0


class TestFinishReasonIsNotDoubled:
    """``finish_reason`` hits the same merge_dicts trap as the provider name.

    Observed live: 8 ledger rows stored ``"stopstop"`` and 3 stored
    ``"tool_callstool_calls"``, because a streamed answer carries more than one
    finish event (one closing the reasoning block, one closing the content) and
    ``merge_dicts`` concatenates equal strings. A doubled value means a query
    for ``length`` can never match, which is the entire reason the field exists
    — a truncation alarm that can never fire.
    """

    def test_a_second_finish_chunk_is_stripped(self) -> None:
        chunk = _gen_chunk(AIMessageChunk(content="", response_metadata={"finish_reason": "stop"}))

        assert _patch._keep_first_response_key(chunk, "finish_reason", 1) == 0
        assert "finish_reason" not in chunk.message.response_metadata

    def test_a_key_present_only_in_generation_info_is_stripped_safely(self) -> None:
        """``finish_reason`` lives in generation_info and is only mirrored onto
        response_metadata by the streaming builder — so a later chunk can carry
        it in one place and not the other. Popping without a default would raise
        on exactly that chunk and kill the stream."""
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(content=""), generation_info={"finish_reason": "stop"}
        )

        assert _patch._keep_first_response_key(chunk, "finish_reason", 1) == 0
        assert chunk.generation_info == {}

    def test_the_first_finish_chunk_is_kept(self) -> None:
        chunk = _gen_chunk(AIMessageChunk(content="", response_metadata={"finish_reason": "stop"}))

        assert _patch._keep_first_response_key(chunk, "finish_reason", 0) == 1
        assert chunk.message.response_metadata["finish_reason"] == "stop"

    def test_a_two_finish_chunk_stream_merges_to_one_value(self) -> None:
        """The end-to-end shape of the live defect: a reasoning finish followed
        by a content finish must merge to ``"stop"``, never ``"stopstop"``."""
        turn = [
            _sse(_chunk("he", provider=UPSTREAM)),
            _sse(_chunk("ll", provider=UPSTREAM, finish="stop")),
            _sse(_chunk("o", provider=UPSTREAM, finish="stop")),
        ]
        with _ScriptedWire(turn) as wire:
            merged = None
            for chunk in _client(wire.base_url).stream("hi"):
                merged = chunk if merged is None else merged + chunk

        assert merged is not None
        assert merged.response_metadata["finish_reason"] == "stop"


class TestStreaming:
    def test_merged_message_reports_the_upstream_exactly_once(self) -> None:
        """The merge_dicts trap: `provider` arrives on every chunk, so an
        unguarded merge would report "StreamLakeStreamLakeStreamLake"."""
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            merged = None
            for chunk in _client(wire.base_url).stream("hi"):
                merged = chunk if merged is None else merged + chunk
        assert merged is not None
        assert merged.response_metadata[PROVIDER_NAME_METADATA_KEY] == UPSTREAM

    def test_exactly_one_chunk_carries_the_upstream(self) -> None:
        """OpenRouter repeats `provider` on all three scripted chunks; only the
        first may come out carrying it, or the merge concatenates the repeats."""
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            metadata = [c.response_metadata for c in _client(wire.base_url).stream("hi")]
        stamped = [m for m in metadata if PROVIDER_NAME_METADATA_KEY in m]
        assert len(stamped) == 1
        assert stamped[0][PROVIDER_NAME_METADATA_KEY] == UPSTREAM

    def test_a_second_finish_event_does_not_double_the_name(self) -> None:
        """Live reasoning streams carry TWO finish events (reasoning block, then
        content), so "the finish chunk" is not a unique slot — measured, not
        hypothetical. First-one-wins is what holds regardless."""
        turn = [
            _sse(_chunk("think", provider=UPSTREAM, finish="stop")),
            _sse(_chunk("answer", provider=UPSTREAM, finish="stop")),
        ]
        with _ScriptedWire(turn) as wire:
            merged = None
            for chunk in _client(wire.base_url).stream("hi"):
                merged = chunk if merged is None else merged + chunk
        assert merged is not None
        assert merged.response_metadata[PROVIDER_NAME_METADATA_KEY] == UPSTREAM

    def test_absent_provider_leaves_the_key_off(self) -> None:
        with _ScriptedWire(_turn(provider=None)) as wire:
            merged = None
            for chunk in _client(wire.base_url).stream("hi"):
                merged = chunk if merged is None else merged + chunk
        assert merged is not None
        assert PROVIDER_NAME_METADATA_KEY not in merged.response_metadata

    def test_the_stop_sequence_and_extra_kwargs_reach_the_provider(self) -> None:
        """The wrapper is a pass-through: everything the caller sent must arrive."""
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            list(_client(wire.base_url).stream("hi", stop=["STOPHERE"], temperature=0.25))
        assert wire.last_request["stop"] == ["STOPHERE"]
        assert wire.last_request["temperature"] == 0.25

    @pytest.mark.asyncio
    async def test_the_async_path_behaves_the_same(self) -> None:
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            merged = None
            async for chunk in _client(wire.base_url).astream(
                "hi", stop=["STOPHERE"], temperature=0.25
            ):
                merged = chunk if merged is None else merged + chunk
            assert wire.last_request["stop"] == ["STOPHERE"]
            assert wire.last_request["temperature"] == 0.25
        assert merged is not None
        assert merged.response_metadata[PROVIDER_NAME_METADATA_KEY] == UPSTREAM

    def test_a_delta_without_a_role_still_gets_the_name(self) -> None:
        """Continuation deltas carry no `role`, so the chunk class comes from
        `default_class` — which the wrapper must keep passing through."""
        chunk = _chunk("x", provider=UPSTREAM, finish="stop")
        del chunk["choices"][0]["delta"]["role"]

        converted = _patch._convert_chunk_to_message_chunk(chunk, AIMessageChunk)

        assert converted.response_metadata[PROVIDER_NAME_METADATA_KEY] == UPSTREAM

    def test_a_non_ai_chunk_is_left_alone(self) -> None:
        """Tool/system deltas have no response_metadata to carry the name."""
        from langchain_core.messages import ToolMessageChunk

        chunk = _chunk("x", provider=UPSTREAM, finish="stop")
        chunk["choices"][0]["delta"] = {"role": "tool", "tool_call_id": "t1", "content": "x"}

        converted = _patch._convert_chunk_to_message_chunk(chunk, ToolMessageChunk)

        assert isinstance(converted, ToolMessageChunk)
        assert PROVIDER_NAME_METADATA_KEY not in converted.response_metadata

    def test_content_and_model_provider_are_untouched(self) -> None:
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            merged = None
            for chunk in _client(wire.base_url).stream("hi"):
                merged = chunk if merged is None else merged + chunk
        assert merged is not None
        assert isinstance(merged, AIMessage)
        assert merged.content == "hello"
        assert merged.response_metadata["model_provider"] == "openrouter"
