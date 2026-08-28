"""Tests for the streaming finish_reason patch.

The OpenRouter SDK types ``ChatStreamChoice.finish_reason`` as required, but
OpenAI-compatible gateways omit it on intermediate reasoning deltas — one such
chunk killed whole streams with a pydantic Unmarshaller error. The patch gives
the field a ``None`` default; a present value must parse exactly as before.

These call ``apply()`` themselves against a field reset to REQUIRED, rather
than asserting the state ``app.patches.__init__`` already installed at import.
The patch mutates a global third-party class, so once anything has applied it
the effect is process-wide and permanent: a test that only validates a chunk
passes whether or not this module's code runs at all, and would keep passing if
``apply()`` were emptied out. Resetting the field first is what makes these
tests able to fail.
"""

from __future__ import annotations

from openrouter.components.chatstreamchoice import ChatStreamChoice
from pydantic import ValidationError
from pydantic_core import PydanticUndefined
import pytest

from app.patches.openrouter_stream_finish_reason_patch import apply

_CHUNK_WITHOUT_REASON = {"delta": {"content": ""}, "index": 0}


@pytest.fixture
def required_finish_reason():
    """Put the field back the way the SDK ships it, then restore after."""
    field = ChatStreamChoice.model_fields["finish_reason"]
    original = field.default
    field.default = PydanticUndefined
    ChatStreamChoice.model_rebuild(force=True)
    try:
        yield field
    finally:
        field.default = original
        ChatStreamChoice.model_rebuild(force=True)


@pytest.mark.unit
class TestFinishReasonPatch:
    def test_apply_makes_an_absent_finish_reason_parse_as_none(
        self, required_finish_reason
    ) -> None:
        # Unpatched, the SDK rejects the exact shape the gateway streams.
        with pytest.raises(ValidationError):
            ChatStreamChoice.model_validate(_CHUNK_WITHOUT_REASON)

        apply()

        assert ChatStreamChoice.model_validate(_CHUNK_WITHOUT_REASON).finish_reason is None

    def test_present_finish_reason_still_parses(self, required_finish_reason) -> None:
        apply()

        chunk = ChatStreamChoice.model_validate(
            {"delta": {"content": "x"}, "index": 0, "finish_reason": "stop"}
        )
        assert chunk.finish_reason == "stop"

    def test_tool_call_chunks_also_tolerate_a_missing_reason(self, required_finish_reason) -> None:
        apply()

        chunk = ChatStreamChoice.model_validate(
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

    def test_a_renamed_field_raises_instead_of_silently_patching_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The SDK dropping or renaming the field must be loud.

        Silently doing nothing would restore the original crash on the next
        gateway that omits the field, with nothing pointing back here.
        """
        monkeypatch.setattr(ChatStreamChoice, "model_fields", {}, raising=False)

        # The whole message, not a substring: it names the class whose field
        # moved, which is the only thing that makes the failure actionable.
        with pytest.raises(AttributeError) as raised:
            apply()
        assert str(raised.value) == ("ChatStreamChoice has no finish_reason field; patch is stale")
