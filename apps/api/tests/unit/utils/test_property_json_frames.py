"""Property-based tests for JSON payload / tool-schema builders.

These builders feed the SSE chat stream and the message-to-tool_data
conversion, so the wire contract is the invariant:

- ``format_sse_response`` / ``format_sse_data`` must always emit a
  ``data: <json>\\n\\n`` frame whose JSON parses and carries the input back
  losslessly — including text with quotes, newlines, and non-ASCII characters.
  An interpolation bug (``str()`` instead of ``json.dumps``) would produce an
  unparseable frame for exactly those inputs.
- ``convert_legacy_tool_data`` must move every non-None legacy tool field into
  a ``tool_data`` entry with a parseable ISO timestamp, never leave a converted
  field at the top level, and preserve pre-existing unified entries.
"""

from datetime import datetime
import json

from hypothesis import given, settings, strategies as st

from app.models.chat_models import tool_fields
from app.utils.agent_utils import format_sse_data, format_sse_response
from app.utils.tool_data_utils import convert_legacy_tool_data

UNICODE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=200
)


class TestSseFrameBuilders:
    @settings(deadline=None)
    @given(content=UNICODE_TEXT)
    def test_response_frame_is_lossless_json(self, content: str) -> None:
        frame = format_sse_response(content)
        assert frame.startswith("data: ")
        assert frame.endswith("\n\n")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {"response": content}

    @settings(deadline=None)
    @given(
        data=st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.one_of(st.text(), st.integers(), st.booleans(), st.none()),
            max_size=10,
        )
    )
    def test_data_frame_preserves_all_keys_and_values(self, data: dict[str, object]) -> None:
        frame = format_sse_data(data)
        assert frame.startswith("data: ")
        assert frame.endswith("\n\n")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == data


JSON_VALUE = st.recursive(
    st.one_of(st.text(max_size=100), st.integers(), st.booleans(), st.none()),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=20), children, max_size=5)
    ),
    max_leaves=20,
)


class TestConvertLegacyToolData:
    @settings(deadline=None)
    @given(
        message=st.dictionaries(
            st.text(min_size=1, max_size=30),
            st.one_of(JSON_VALUE, st.lists(JSON_VALUE, max_size=3)),
            max_size=8,
        )
    )
    def test_legacy_fields_convert_and_nothing_else_changes(
        self, message: dict[str, object]
    ) -> None:
        output = convert_legacy_tool_data(message)
        # The output must always be a JSON-serializable dict.
        assert json.dumps(output) is not None

        legacy_present = {
            field: message[field]
            for field in tool_fields
            if field != "tool_data" and message.get(field) is not None
        }
        # Every non-None legacy field must be converted: removed from the top
        # level and represented exactly once in tool_data.
        if legacy_present:
            entries = output.get("tool_data")
            assert isinstance(entries, list), output
            converted = [
                e for e in entries if isinstance(e, dict) and e.get("tool_name") in legacy_present
            ]
            assert len(converted) == len(legacy_present)
            for entry in converted:
                field = entry["tool_name"]
                assert field not in output
                assert entry["data"] == legacy_present[field]
                # Timestamp must be a real ISO datetime, not a placeholder.
                assert isinstance(entry["timestamp"], str)
                datetime.fromisoformat(entry["timestamp"])
        for field in legacy_present:
            assert field not in output

        # Pre-existing unified entries must be preserved, in order.
        existing = message.get("tool_data")
        if isinstance(existing, list) and existing:
            entries = output.get("tool_data")
            assert isinstance(entries, list)
            assert entries[: len(existing)] == existing

        # Non-tool fields must pass through untouched.
        for key, value in message.items():
            if key not in tool_fields:
                assert output[key] == value
