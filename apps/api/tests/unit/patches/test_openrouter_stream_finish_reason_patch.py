"""Tests for the streaming finish_reason patch.

The OpenRouter SDK types ``ChatStreamChoice.finish_reason`` as required, but
OpenAI-compatible gateways omit it on intermediate reasoning deltas — one such
chunk killed whole streams with a pydantic Unmarshaller error. The patch gives
the field a ``None`` default; a present value must parse exactly as before.
"""

from __future__ import annotations

from openrouter.components.chatstreamchoice import ChatStreamChoice
import pytest

# Import applies the patch (module-level apply()).
import app.patches.openrouter_stream_finish_reason_patch as patch_module  # noqa: F401  # import applies the monkeypatch at module level; the symbol itself is unused


def _chunk(payload: dict) -> ChatStreamChoice:
    return ChatStreamChoice.model_validate(payload)


@pytest.mark.unit
class TestFinishReasonPatch:
    def test_chunk_without_finish_reason_validates_to_none(self) -> None:
        # The exact shape the opencode zen gateway streams on reasoning deltas.
        chunk = _chunk({"delta": {"content": ""}, "index": 0})
        assert chunk.finish_reason is None

    def test_present_finish_reason_still_parses(self) -> None:
        chunk = _chunk({"delta": {"content": "x"}, "index": 0, "finish_reason": "stop"})
        assert chunk.finish_reason == "stop"

    def test_tool_call_chunks_also_tolerate_a_missing_reason(self) -> None:
        chunk = _chunk(
            {
                "delta": {
                    "tool_calls": [
                        {"index": 0, "id": "c1", "function": {"name": "f", "arguments": "{}"}}
                    ]
                },
                "index": 0,
            }
        )
        assert chunk.finish_reason is None
        assert chunk.delta.tool_calls[0].function.name == "f"
