"""Unit tests for app.utils.stream_utils."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.stream_utils import extract_tool_entries_from_update


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ai_message(
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> MagicMock:
    """Return a mock AIMessage with a .tool_calls attribute."""
    msg = MagicMock()
    msg.tool_calls = tool_calls or []
    return msg


def _make_plain_message() -> MagicMock:
    """Return a mock message without a tool_calls attribute (e.g. HumanMessage)."""
    msg = MagicMock(spec=[])  # spec=[] means no attributes
    return msg


# ---------------------------------------------------------------------------
# extract_tool_entries_from_update
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractToolEntriesFromUpdate:
    """Tests for extract_tool_entries_from_update."""

    # -- empty / invalid inputs --

    async def test_empty_dict_returns_empty_list(self) -> None:
        result = await extract_tool_entries_from_update({}, set())
        assert result == []

    async def test_non_dict_input_returns_empty_list(self) -> None:
        result = await extract_tool_entries_from_update("not a dict", set())  # type: ignore[arg-type]
        assert result == []

    async def test_dict_without_messages_key_returns_empty(self) -> None:
        result = await extract_tool_entries_from_update({"foo": "bar"}, set())
        assert result == []

    async def test_messages_with_no_tool_calls_returns_empty(self) -> None:
        msg = _make_ai_message(tool_calls=[])
        result = await extract_tool_entries_from_update({"messages": [msg]}, set())
        assert result == []

    async def test_message_without_tool_calls_attr_skipped(self) -> None:
        msg = _make_plain_message()
        result = await extract_tool_entries_from_update({"messages": [msg]}, set())
        assert result == []

    # -- single tool call --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_single_tool_call_extracted(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data", "data": {}}

        tc = {"id": "tc-1", "name": "search", "args": {}}
        msg = _make_ai_message([tc])
        emitted: set[str] = set()

        result = await extract_tool_entries_from_update({"messages": [msg]}, emitted)

        assert len(result) == 1
        assert result[0][0] == "tc-1"
        assert "tc-1" in emitted
        mock_format.assert_awaited_once()

    # -- deduplication --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_already_emitted_ids_are_skipped(
        self, mock_format: AsyncMock
    ) -> None:
        tc = {"id": "tc-dup", "name": "search", "args": {}}
        msg = _make_ai_message([tc])
        emitted: set[str] = {"tc-dup"}

        result = await extract_tool_entries_from_update({"messages": [msg]}, emitted)

        assert result == []
        mock_format.assert_not_awaited()

    # -- tool call with no id is skipped --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_tool_call_without_id_skipped(self, mock_format: AsyncMock) -> None:
        tc: dict[str, object] = {"id": None, "name": "search", "args": {}}
        msg = _make_ai_message([tc])

        result = await extract_tool_entries_from_update({"messages": [msg]}, set())

        assert result == []
        mock_format.assert_not_awaited()

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_tool_call_missing_id_key_skipped(
        self, mock_format: AsyncMock
    ) -> None:
        """tc.get("id") returns None when key is absent."""
        tc = {"name": "search", "args": {}}
        msg = _make_ai_message([tc])

        result = await extract_tool_entries_from_update({"messages": [msg]}, set())

        assert result == []

    # -- format_tool_call_entry returns None --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_none_entry_from_formatter_excluded(
        self, mock_format: AsyncMock
    ) -> None:
        mock_format.return_value = None
        tc = {"id": "tc-nil", "name": "unknown", "args": {}}
        msg = _make_ai_message([tc])
        emitted: set[str] = set()

        result = await extract_tool_entries_from_update({"messages": [msg]}, emitted)

        assert result == []
        # The id is still added to emitted — verify via the code
        # Actually the code only adds to emitted if tool_entry is truthy
        assert "tc-nil" not in emitted

    # -- multiple tool calls across multiple messages --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_multiple_messages_multiple_tool_calls(
        self, mock_format: AsyncMock
    ) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}

        msg1 = _make_ai_message(
            [
                {"id": "a1", "name": "t1", "args": {}},
                {"id": "a2", "name": "t2", "args": {}},
            ]
        )
        msg2 = _make_ai_message(
            [
                {"id": "a3", "name": "t3", "args": {}},
            ]
        )
        emitted: set[str] = set()

        result = await extract_tool_entries_from_update(
            {"messages": [msg1, msg2]}, emitted
        )

        assert len(result) == 3
        assert {r[0] for r in result} == {"a1", "a2", "a3"}
        assert emitted == {"a1", "a2", "a3"}

    # -- integration_metadata forwarding --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_integration_metadata_forwarded(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        metadata = {
            "icon_url": "https://img.com/icon.png",
            "integration_id": "gmail",
            "name": "Gmail",
        }
        tc = {"id": "tc-m", "name": "send_email", "args": {}}
        msg = _make_ai_message([tc])

        await extract_tool_entries_from_update(
            {"messages": [msg]}, set(), integration_metadata=metadata
        )

        call_kwargs = mock_format.call_args[1]
        assert call_kwargs["icon_url"] == "https://img.com/icon.png"
        assert call_kwargs["integration_id"] == "gmail"
        assert call_kwargs["integration_name"] == "Gmail"

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_no_integration_metadata_passes_none(
        self, mock_format: AsyncMock
    ) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        tc = {"id": "tc-n", "name": "search", "args": {}}
        msg = _make_ai_message([tc])

        await extract_tool_entries_from_update(
            {"messages": [msg]}, set(), integration_metadata=None
        )

        call_kwargs = mock_format.call_args[1]
        assert call_kwargs["icon_url"] is None
        assert call_kwargs["integration_id"] is None
        assert call_kwargs["integration_name"] is None

    # -- mixed messages (some with tool_calls, some without) --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_mixed_message_types(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}

        human_msg = _make_plain_message()
        ai_msg = _make_ai_message([{"id": "tc-mix", "name": "search", "args": {}}])
        empty_ai_msg = _make_ai_message([])

        result = await extract_tool_entries_from_update(
            {"messages": [human_msg, ai_msg, empty_ai_msg]}, set()
        )

        assert len(result) == 1
        assert result[0][0] == "tc-mix"

    # -- emitted_tool_calls is mutated in place --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_emitted_set_mutated_in_place(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        tc = {"id": "tc-mut", "name": "tool", "args": {}}
        msg = _make_ai_message([tc])
        emitted: set[str] = set()

        await extract_tool_entries_from_update({"messages": [msg]}, emitted)

        assert "tc-mut" in emitted

    # -- partial integration_metadata (missing keys) --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_partial_integration_metadata(self, mock_format: AsyncMock) -> None:
        """integration_metadata with only icon_url set."""
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        metadata: Dict[str, Any] = {"icon_url": "https://icon.com/x.png"}
        tc = {"id": "tc-p", "name": "search", "args": {}}
        msg = _make_ai_message([tc])

        await extract_tool_entries_from_update(
            {"messages": [msg]}, set(), integration_metadata=metadata
        )

        call_kwargs = mock_format.call_args[1]
        assert call_kwargs["icon_url"] == "https://icon.com/x.png"
        assert call_kwargs["integration_id"] is None
        assert call_kwargs["integration_name"] is None

    # -- duplicate ids in same batch --

    @patch(
        "app.utils.stream_utils.format_tool_call_entry",
        new_callable=AsyncMock,
    )
    async def test_duplicate_id_within_same_update_deduped(
        self, mock_format: AsyncMock
    ) -> None:
        """If two tool calls in the same update share an id, only the first is emitted."""
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        tc1 = {"id": "same-id", "name": "t1", "args": {}}
        tc2 = {"id": "same-id", "name": "t2", "args": {}}
        msg = _make_ai_message([tc1, tc2])

        result = await extract_tool_entries_from_update({"messages": [msg]}, set())

        assert len(result) == 1
        assert result[0][0] == "same-id"
