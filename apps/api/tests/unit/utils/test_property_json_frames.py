"""Property-based tests for JSON payload / tool-schema builders.

These builders feed the SSE chat stream and the message-to-tool_data
conversion, so the wire contract is the invariant:

- convert_legacy_tool_data must move every non-None legacy tool field into
  a tool_data entry with a parseable ISO timestamp, never leave a converted
  field at the top level, and preserve pre-existing unified entries.
"""

from datetime import datetime
import json

from hypothesis import given, settings, strategies as st

from app.db.repositories.conversation_entries_legacy import convert_legacy_tool_data
from app.models.chat_models import tool_fields

JSON_VALUE = st.recursive(
    st.one_of(st.text(max_size=100), st.integers(), st.booleans(), st.none()),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=20), children, max_size=5)
    ),
    max_leaves=20,
)


LEGACY_FIELD = next(field for field in tool_fields if field != "tool_data")


class TestConvertLegacyToolDataExamples:
    def test_existing_entries_come_first_and_the_legacy_field_is_appended(self) -> None:
        existing = {"tool_name": "search_results", "data": {"q": "x"}}
        output = convert_legacy_tool_data({"tool_data": [existing], LEGACY_FIELD: {"v": 1}})

        entries = output["tool_data"]
        assert isinstance(entries, list)
        assert entries[0] == existing
        assert [(e["tool_name"], e["data"]) for e in entries[1:]] == [(LEGACY_FIELD, {"v": 1})]
        assert LEGACY_FIELD not in output

    def test_an_empty_tool_data_list_is_left_as_it_was(self) -> None:
        assert convert_legacy_tool_data({"tool_data": [], "content": "hi"}) == {
            "tool_data": [],
            "content": "hi",
        }


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
