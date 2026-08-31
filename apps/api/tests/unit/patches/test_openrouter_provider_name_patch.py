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

from langchain_core.messages import AIMessage
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

    def test_wrappers_delegate_to_the_captured_originals(self) -> None:
        """The originals must be the library's, not our own wrappers — a
        self-referential capture would recurse forever on the first call."""
        assert _patch._ORIGINAL_CREATE_CHAT_RESULT is not _patch._create_chat_result
        assert _patch._ORIGINAL_CONVERT_CHUNK is not _patch._convert_chunk_to_message_chunk


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

    def test_only_the_final_chunk_carries_the_upstream(self) -> None:
        """Response-level data goes on the finish_reason chunk, once.

        OpenRouter repeats `provider` on all three scripted chunks; exactly one
        of them may come out carrying it, or the merge concatenates the repeats.
        """
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            metadata = [c.response_metadata for c in _client(wire.base_url).stream("hi")]
        stamped = [m for m in metadata if PROVIDER_NAME_METADATA_KEY in m]
        assert len(stamped) == 1
        assert stamped[0][PROVIDER_NAME_METADATA_KEY] == UPSTREAM
        # It is the terminal chunk — the one the library puts model_name/id on.
        assert stamped[0]["finish_reason"] == "stop"

    def test_intermediate_chunks_are_left_alone(self) -> None:
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            metadata = [c.response_metadata for c in _client(wire.base_url).stream("hi")]
        intermediate = [m for m in metadata if "model_provider" in m and "finish_reason" not in m]
        assert len(intermediate) == 2, "expected two non-terminal chunks"
        assert all(PROVIDER_NAME_METADATA_KEY not in m for m in intermediate)

    def test_absent_provider_leaves_the_key_off(self) -> None:
        with _ScriptedWire(_turn(provider=None)) as wire:
            merged = None
            for chunk in _client(wire.base_url).stream("hi"):
                merged = chunk if merged is None else merged + chunk
        assert merged is not None
        assert PROVIDER_NAME_METADATA_KEY not in merged.response_metadata

    def test_content_and_model_provider_are_untouched(self) -> None:
        with _ScriptedWire(_turn(provider=UPSTREAM)) as wire:
            merged = None
            for chunk in _client(wire.base_url).stream("hi"):
                merged = chunk if merged is None else merged + chunk
        assert merged is not None
        assert isinstance(merged, AIMessage)
        assert merged.content == "hello"
        assert merged.response_metadata["model_provider"] == "openrouter"
