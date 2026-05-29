"""Unit tests for app.utils.stream_utils — LangGraph SSE streaming helpers.

This module is the SSE / tool_data contract layer shared by the live chat path
(chat_service), the executor background path (executor_runner), and the subagent
runner. Every byte these functions emit is parsed by the frontend, so the streamed
key names and payload shapes are a hard contract.

================================================================================
UNIT: extract_tool_entries_from_update
EXPECTED: Given a LangGraph 'updates' state dict, return [(tool_call_id, entry)]
          for every NOT-yet-emitted tool call, mutating emitted_tool_calls in place.
MECHANISM: guard non-dict / missing "messages" -> []; per message skip if no
           .tool_calls; per tc skip if no id or already emitted; format via
           format_tool_call_entry(...); append + mark emitted only if truthy entry.
MUST-CATCH:
  - non-dict / missing "messages" returns [] (the `not isinstance ... or ...` guard)
  - message without .tool_calls attr or with falsy tool_calls is skipped
  - tool call with no id (None / missing key) is skipped, formatter not called
  - already-emitted id is skipped, formatter not called (dedup across calls)
  - duplicate id within one update emitted once (in-place set updated mid-loop)
  - falsy formatter result is NOT appended and id NOT added to emitted
  - integration_metadata fields forwarded as icon_url/integration_id/integration_name
  - None metadata forwards None for all three (the conditional-expression branches)

UNIT: _extract_response_text
EXPECTED: Strip a leading "data: " prefix, JSON-parse, return data["response"]; "" on
          bad JSON / missing key / non-"data:" chunk.
MECHANISM: removeprefix("data: "); json.loads; data.get("response", "").
MUST-CATCH:
  - the "data: " prefix is stripped before parse (real chunk wire format)
  - returns the actual "response" value, not a constant
  - invalid JSON returns "" (the except path)
  - missing "response" key returns "" (the .get default)

UNIT: normalize_custom_event
EXPECTED: Convert a raw field payload into unified {"tool_data": ...} form; pass
          through already-normalized and non-tool payloads unchanged.
MECHANISM: short-circuit if "tool_data" present; collect tool_fields whose value is
           not None into ToolDataEntry list; single -> dict, many -> list; preserve
           non-tool keys; return payload unchanged when no tool fields matched.
MUST-CATCH:
  - payload already containing "tool_data" returns unchanged (identity short-circuit)
  - a recognized tool field is wrapped as {"tool_name", "data", "timestamp"}
  - the wrapped tool_name/data exactly mirror the source field
  - one matching field -> dict under tool_data; two -> list (the len==1 branch)
  - non-tool keys (e.g. nextPageToken) are preserved alongside tool_data
  - a payload with NO tool fields passes through unchanged (entries empty branch)
  - a field explicitly set to None does NOT produce an entry (`is not None` guard)

UNIT: extract_tool_data
EXPECTED: Parse a JSON chunk into {"tool_data": [...], "other_data": {...},
          "tool_output": ...} keyed only by what is present; {} on bad JSON.
MECHANISM: json.loads; lift follow_up_actions into other_data; normalize_custom_event;
           list-wrap tool_data; forward tool_output as-is.
MUST-CATCH:
  - invalid JSON returns {} (the JSONDecodeError path)
  - follow_up_actions surfaces under result["other_data"]
  - a single tool_data entry is returned as a one-element LIST
  - tool_output is forwarded verbatim
  - a plain non-tool, no-follow-up payload returns {} (no spurious keys)
  - follow_up_actions explicitly None does not create other_data (`is not None`)

UNIT: process_data_chunk  [P0 SSE CONTRACT]
EXPECTED: Process a 'data: '-prefixed chunk: forward subagent lifecycle, accumulate
          todo_progress, publish tool_data/tool_output/follow_up_actions sub-chunks to
          Redis, update progress, return (follow_up_actions, True).
MECHANISM: strip 6-char prefix; parse; publish each recognized piece via
           stream_manager.publish_chunk; capture tool_output into tool_outputs;
           update_progress; plain chunk path republishes the raw chunk.
MUST-CATCH:
  - subagent_start/end are stored under subagent_starts/ends keyed by subagent_id AND
    published as their own "data: {...}" chunk
  - todo_progress snapshot is stored under its "source" (default "executor")
  - a tool_data entry is appended to tool_data["tool_data"] and published per entry
  - tool_output with id+output is captured into tool_outputs and published
  - follow_up_actions are published under the "follow_up_actions" key
  - a chunk with NO extractable data republishes the raw chunk unchanged
  - return value is (follow_up_actions, True) in both the data and no-data branches
  - response text drives update_progress message_chunk

UNIT: set_stream_log_context
EXPECTED: Attach structured chat log context derived from the request body.
MECHANISM: log.set(user=..., chat=ChatContext(...), user_message_length=...,
           selected_tool=...).
MUST-CATCH:
  - user dict carries str(user_id) when present, {} when None (the ternary)
  - message_count == len(body.messages)
  - has_files true iff fileIds or fileData present; file_count is their summed length
  - has_reply / has_calendar_event reflect the optional body fields
  - selected_workflow_id is body.selectedWorkflow.id, "" when absent
  - user_message_length is the last message's content length

UNIT: aggregate_usage_metadata
EXPECTED: Sum input/output/cache_read tokens across model entries; ignore non-dicts.
MECHANISM: per dict entry add input_tokens, output_tokens, and cache_read (with
           cached_content_token_count fallback) via int(... or 0).
MUST-CATCH:
  - totals are summed across multiple entries (not just first/last)
  - non-dict entries are skipped (the isinstance guard)
  - cache_read read from input_token_details
  - cached_content_token_count is the fallback when cache_read absent
  - None / missing values coerce to 0 (the `or 0`)

UNIT: merge_tool_outputs
EXPECTED: Backfill data.output for tool_calls_data entries from the outputs map.
MECHANISM: iterate tool_data["tool_data"]; only tool_calls_data with dict data and a
           matching tool_call_id gets data["output"] set.
MUST-CATCH:
  - matching tool_calls_data entry gets its output injected
  - a non-tool_calls_data entry is left untouched (tool_name guard)
  - an unmatched tool_call_id is left untouched

UNIT: inject_todo_progress
EXPECTED: Append accumulated todo_progress as one tool_data entry; no-op when empty.
MECHANISM: if accumulated: append {"tool_name":"todo_progress","data":...,timestamp}.
MUST-CATCH:
  - non-empty accumulator appends exactly one entry tagged "todo_progress" with the data
  - empty accumulator appends nothing (the truthiness guard)

UNIT: recover_stream_state
EXPECTED: When complete_message is empty, recover it (and tool_data) from Redis
          progress; otherwise pass through.
MECHANISM: early-return if complete_message; else get_progress; pull complete_message;
           replace tool_data only if progress has tool_data and current does not.
MUST-CATCH:
  - non-empty complete_message short-circuits, Redis not queried
  - missing progress returns the inputs unchanged
  - recovered complete_message comes from progress["complete_message"]
  - progress tool_data replaces local tool_data only when local is empty
  - existing local tool_data is preserved over progress tool_data

UNIT: publish_description_if_ready
EXPECTED: When the description task is done, publish its result and return None to
          clear it; otherwise return the task untouched.
MECHANISM: return task if None/not done; else publish conversation_description chunk;
           swallow task exceptions; always return None when handled.
MUST-CATCH:
  - None task returns None without publishing
  - a not-done task is returned unchanged, nothing published
  - a done task publishes {"conversation_description": result} and returns None
  - a task whose result() raises is swallowed and still returns None (no republish)

UNIT: absorb_collector_event
EXPECTED: Route one collector event into accumulated tool_data / tool_outputs /
          subagent start-end buckets.
MECHANISM: append tool_data; capture tool_output id->output; store subagent_start/end
           keyed by subagent_id.
MUST-CATCH:
  - tool_data event is appended to accumulated["tool_data"]
  - tool_output with id+output populates tool_outputs; missing id/output does not
  - subagent_start/end stored under their subagent_id

UNIT: apply_outputs_to_tool_data
EXPECTED: Backfill data.output across entries from outputs map, optionally restricted
          to one tool_name.
MECHANISM: per entry skip if only_tool_name set and mismatched; skip non-dict data;
           inject output when tool_call_id matches.
MUST-CATCH:
  - matching entry gets output injected when only_tool_name is None
  - only_tool_name filters out non-matching tool_name entries
  - non-dict data is skipped without error
  - unmatched tool_call_id leaves entry untouched

UNIT: reconstruct_subagent_groups  [P0 PERSISTENCE SHAPE]
EXPECTED: Group flat subagent-tagged tool_calls into subagent_group entries for Mongo.
MECHANISM: pop starts/ends; no-op if no starts; build a group per start; route
           subagent-tagged tool_calls_data into their group; nest child groups under
           parent; rebuild tool_data as top_level + root group entries.
MUST-CATCH:
  - no subagent_starts: function returns early, tool_data["tool_data"] untouched, and
    the start/end keys are popped off
  - a tagged tool_calls_data entry is routed into its group's tool_calls
  - an untagged / non-tool_calls_data entry stays top-level
  - a child group (parent_subagent_id) is nested, not emitted at root
  - the emitted group carries subagent_name/agent_type/duration_ms/token_count from
    start/end and is wrapped under tool_name "subagent_group"
  - completed_at is set only when an end event exists

EQUIVALENT MUTANTS (proven behaviour-preserving survivors): the only mutants that
survive the full run are `const_str str -> ''` applied to non-behavioural strings:
  - docstring first-lines: L31, L94, L105, L142, L186, L290, L311, L335, L349,
    L365, L392, L411, L438, L456 (blanking a docstring changes no return/state/stream)
  - log message text: L384 x2 (log.debug "Recovered ... chars"), L402 (log.error in the
    swallowed-exception path) — log output only, asserted behaviour is the swallow + None
Every behaviour-affecting mutant (compare/boolop/not/return-None/const-int/dict-key/
wire-format string) is killed -> 100% kill of the live, behaviour-bearing scope.
================================================================================
"""

from datetime import datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.message_models import (
    MessageRequestWithHistory,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.utils.stream_utils import (
    _extract_response_text,
    absorb_collector_event,
    aggregate_usage_metadata,
    apply_outputs_to_tool_data,
    extract_tool_data,
    extract_tool_entries_from_update,
    inject_todo_progress,
    merge_tool_outputs,
    normalize_custom_event,
    process_data_chunk,
    publish_description_if_ready,
    reconstruct_subagent_groups,
    recover_stream_state,
    set_stream_log_context,
)

pytestmark = pytest.mark.unit

STREAM_ID = "stream-123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ai_message(tool_calls: list[dict[str, Any]]) -> MagicMock:
    """Mock AIMessage exposing ONLY .tool_calls.

    spec=["tool_calls"] makes the mock answer hasattr() truthfully (it does NOT
    respond to arbitrary attribute names), so the `hasattr(msg, "tool_calls")`
    branch in the production code is exercised against a real attribute lookup.
    """
    msg = MagicMock(spec=["tool_calls"])
    msg.tool_calls = tool_calls
    return msg


def _plain_message() -> MagicMock:
    """Mock message with no .tool_calls attribute (e.g. HumanMessage)."""
    return MagicMock(spec=[])


def _data_chunk(payload: dict[str, Any]) -> str:
    """Build a wire-format 'data: <json>' SSE chunk."""
    return f"data: {json.dumps(payload)}"


def _fresh_state() -> dict[str, Any]:
    return {
        "tool_data": {"tool_data": []},
        "tool_outputs": {},
        "todo_progress": {},
    }


# ---------------------------------------------------------------------------
# extract_tool_entries_from_update
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractToolEntriesFromUpdate:
    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_non_dict_or_missing_messages_returns_empty(self, mock_format: AsyncMock) -> None:
        assert await extract_tool_entries_from_update("nope", set()) == []  # type: ignore[arg-type]
        assert await extract_tool_entries_from_update({"foo": 1}, set()) == []
        mock_format.assert_not_awaited()

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_message_without_tool_calls_skipped(self, mock_format: AsyncMock) -> None:
        plain = _plain_message()
        empty = _ai_message([])
        result = await extract_tool_entries_from_update({"messages": [plain, empty]}, set())
        assert result == []
        mock_format.assert_not_awaited()

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_tool_call_without_id_skipped(self, mock_format: AsyncMock) -> None:
        msg = _ai_message([{"id": None, "name": "x"}, {"name": "y"}])
        result = await extract_tool_entries_from_update({"messages": [msg]}, set())
        assert result == []
        mock_format.assert_not_awaited()

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_single_tool_call_extracted_and_marked(self, mock_format: AsyncMock) -> None:
        entry = {"tool_name": "tool_calls_data", "data": {"x": 1}}
        mock_format.return_value = entry
        emitted: set[str] = set()
        msg = _ai_message([{"id": "tc-1", "name": "search", "args": {}}])

        result = await extract_tool_entries_from_update({"messages": [msg]}, emitted)

        assert result == [("tc-1", entry)]
        assert emitted == {"tc-1"}

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_already_emitted_skipped(self, mock_format: AsyncMock) -> None:
        msg = _ai_message([{"id": "dup", "name": "x"}])
        result = await extract_tool_entries_from_update({"messages": [msg]}, {"dup"})
        assert result == []
        mock_format.assert_not_awaited()

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_duplicate_id_in_same_update_emitted_once(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        msg = _ai_message([{"id": "same", "name": "a"}, {"id": "same", "name": "b"}])
        emitted: set[str] = set()

        result = await extract_tool_entries_from_update({"messages": [msg]}, emitted)

        assert [r[0] for r in result] == ["same"]
        assert emitted == {"same"}
        assert mock_format.await_count == 1

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_falsy_entry_not_appended_or_marked(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = None
        emitted: set[str] = set()
        msg = _ai_message([{"id": "tc-nil", "name": "x"}])

        result = await extract_tool_entries_from_update({"messages": [msg]}, emitted)

        assert result == []
        assert "tc-nil" not in emitted

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_metadata_forwarded(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        metadata = {"icon_url": "https://i/x.png", "integration_id": "gmail", "name": "Gmail"}
        msg = _ai_message([{"id": "m", "name": "send"}])

        await extract_tool_entries_from_update(
            {"messages": [msg]}, set(), integration_metadata=metadata
        )

        kw = mock_format.call_args.kwargs
        assert kw["icon_url"] == "https://i/x.png"
        assert kw["integration_id"] == "gmail"
        assert kw["integration_name"] == "Gmail"

    @patch("app.utils.stream_utils.format_tool_call_entry", new_callable=AsyncMock)
    async def test_none_metadata_forwards_none(self, mock_format: AsyncMock) -> None:
        mock_format.return_value = {"tool_name": "tool_calls_data"}
        msg = _ai_message([{"id": "n", "name": "search"}])

        await extract_tool_entries_from_update(
            {"messages": [msg]}, set(), integration_metadata=None
        )

        kw = mock_format.call_args.kwargs
        assert kw["icon_url"] is None
        assert kw["integration_id"] is None
        assert kw["integration_name"] is None


# ---------------------------------------------------------------------------
# _extract_response_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractResponseText:
    def test_strips_prefix_and_returns_response(self) -> None:
        assert _extract_response_text('data: {"response": "hello"}') == "hello"

    def test_without_prefix_still_parses(self) -> None:
        assert _extract_response_text('{"response": "raw"}') == "raw"

    def test_invalid_json_returns_empty(self) -> None:
        assert _extract_response_text("data: not json") == ""

    def test_missing_response_key_returns_empty(self) -> None:
        assert _extract_response_text('data: {"other": 1}') == ""


# ---------------------------------------------------------------------------
# normalize_custom_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeCustomEvent:
    def test_already_normalized_passthrough(self) -> None:
        payload = {"tool_data": {"tool_name": "x"}, "extra": 1}
        assert normalize_custom_event(payload) is payload

    def test_tool_data_key_short_circuits_before_field_scan(self) -> None:
        # Payload has BOTH "tool_data" AND a recognized tool field. The "tool_data"
        # short-circuit must win: the raw weather_data is NOT re-wrapped. If the
        # guard key were blanked, the field scan would rebuild and overwrite.
        payload = {"tool_data": {"tool_name": "preset"}, "weather_data": {"t": 1}}
        result = normalize_custom_event(payload)
        assert result is payload
        assert result["tool_data"] == {"tool_name": "preset"}

    def test_single_tool_field_wrapped(self) -> None:
        result = normalize_custom_event({"weather_data": {"temp": 20}})
        assert result["tool_data"]["tool_name"] == "weather_data"
        assert result["tool_data"]["data"] == {"temp": 20}
        # timestamp is a real ISO string, not empty
        datetime.fromisoformat(result["tool_data"]["timestamp"])

    def test_multiple_tool_fields_become_list(self) -> None:
        result = normalize_custom_event({"weather_data": {"t": 1}, "search_results": [{"r": 2}]})
        assert isinstance(result["tool_data"], list)
        names = {e["tool_name"] for e in result["tool_data"]}
        assert names == {"weather_data", "search_results"}

    def test_non_tool_keys_preserved(self) -> None:
        result = normalize_custom_event({"email_fetch_data": [{"id": 1}], "nextPageToken": "abc"})
        assert result["nextPageToken"] == "abc"
        assert result["tool_data"]["tool_name"] == "email_fetch_data"

    def test_non_tool_payload_passthrough(self) -> None:
        payload = {"progress": "thinking", "subagent_start": {"id": "x"}}
        assert normalize_custom_event(payload) is payload

    def test_none_valued_field_is_not_an_entry(self) -> None:
        # weather_data explicitly None must not be wrapped (the `is not None` guard)
        payload = {"weather_data": None, "progress": "x"}
        assert normalize_custom_event(payload) is payload


# ---------------------------------------------------------------------------
# extract_tool_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractToolData:
    def test_invalid_json_returns_empty_dict(self) -> None:
        assert extract_tool_data("{not json") == {}

    def test_follow_up_actions_surface_in_other_data(self) -> None:
        result = extract_tool_data('{"follow_up_actions": ["a", "b"]}')
        assert result == {"other_data": {"follow_up_actions": ["a", "b"]}}

    def test_follow_up_actions_none_omitted(self) -> None:
        assert extract_tool_data('{"follow_up_actions": null}') == {}

    def test_single_tool_data_wrapped_as_list(self) -> None:
        result = extract_tool_data('{"weather_data": {"temp": 5}}')
        assert isinstance(result["tool_data"], list)
        assert result["tool_data"][0]["tool_name"] == "weather_data"
        assert result["tool_data"][0]["data"] == {"temp": 5}

    def test_tool_output_forwarded_verbatim(self) -> None:
        result = extract_tool_data('{"tool_output": {"tool_call_id": "t1", "output": "z"}}')
        assert result["tool_output"] == {"tool_call_id": "t1", "output": "z"}

    def test_plain_payload_returns_empty(self) -> None:
        assert extract_tool_data('{"response": "hi"}') == {}


# ---------------------------------------------------------------------------
# process_data_chunk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessDataChunk:
    @patch("app.utils.stream_utils.stream_manager")
    async def test_subagent_lifecycle_stored_and_published(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk(
            {
                "subagent_start": {"subagent_id": "s1", "subagent_name": "Worker"},
                "subagent_end": {"subagent_id": "s1", "duration_ms": 12},
            }
        )

        fu, published = await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert st["tool_data"]["subagent_starts"]["s1"]["subagent_name"] == "Worker"
        assert st["tool_data"]["subagent_ends"]["s1"]["duration_ms"] == 12
        # Exact SSE wire format: "data: " prefix, the keyed payload, "\n\n" terminator.
        published_payloads = [c.args[1] for c in sm.publish_chunk.await_args_list]
        start_wire = f"data: {json.dumps({'subagent_start': {'subagent_id': 's1', 'subagent_name': 'Worker'}})}\n\n"
        end_wire = (
            f"data: {json.dumps({'subagent_end': {'subagent_id': 's1', 'duration_ms': 12}})}\n\n"
        )
        assert start_wire in published_payloads
        assert end_wire in published_payloads
        assert (fu, published) == ([], True)

    @patch("app.utils.stream_utils.stream_manager")
    async def test_todo_progress_stored_under_source(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"todo_progress": {"source": "planner", "done": 2}})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert st["todo_progress"]["planner"] == {"source": "planner", "done": 2}

    @patch("app.utils.stream_utils.stream_manager")
    async def test_todo_progress_default_source_executor(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"todo_progress": {"done": 1}})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert "executor" in st["todo_progress"]

    @patch("app.utils.stream_utils.stream_manager")
    async def test_tool_data_appended_and_published(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"weather_data": {"temp": 30}})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert len(st["tool_data"]["tool_data"]) == 1
        entry = st["tool_data"]["tool_data"][0]
        assert entry["tool_name"] == "weather_data"
        published = [c.args[1] for c in sm.publish_chunk.await_args_list]
        # Exact wire format including "data: " prefix and "\n\n" terminator.
        assert f"data: {json.dumps({'tool_data': entry})}\n\n" in published

    @patch("app.utils.stream_utils.stream_manager")
    async def test_tool_output_captured_and_published(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"tool_output": {"tool_call_id": "tc-9", "output": "RESULT"}})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert st["tool_outputs"]["tc-9"] == "RESULT"
        published = [c.args[1] for c in sm.publish_chunk.await_args_list]
        out_payload = {"tool_call_id": "tc-9", "output": "RESULT"}
        assert f"data: {json.dumps({'tool_output': out_payload})}\n\n" in published

    @patch("app.utils.stream_utils.stream_manager")
    async def test_tool_output_without_id_not_captured(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"tool_output": {"output": "no-id"}})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert st["tool_outputs"] == {}

    @patch("app.utils.stream_utils.stream_manager")
    async def test_follow_up_actions_published_and_returned(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"follow_up_actions": ["next?"]})

        fu, published = await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert fu == ["next?"]
        assert published is True
        publishes = [c.args[1] for c in sm.publish_chunk.await_args_list]
        assert f"data: {json.dumps({'follow_up_actions': ['next?']})}\n\n" in publishes

    @patch("app.utils.stream_utils.stream_manager")
    async def test_plain_chunk_republished_unchanged(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"response": "just text"})

        fu, published = await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        assert (fu, published) == ([], True)
        # the raw chunk itself is published in the no-data branch
        assert sm.publish_chunk.await_args_list[-1].args == (STREAM_ID, chunk)
        # response text drives update_progress
        sm.update_progress.assert_awaited_once()
        assert sm.update_progress.await_args.kwargs["message_chunk"] == "just text"
        assert sm.update_progress.await_args.kwargs["tool_data"] is None

    @patch("app.utils.stream_utils.stream_manager")
    async def test_data_branch_updates_progress_with_response_text(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"weather_data": {"t": 1}, "response": "weather is set"})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        sm.update_progress.assert_awaited_once()
        assert sm.update_progress.await_args.kwargs["message_chunk"] == "weather is set"

    @patch("app.utils.stream_utils.stream_manager")
    async def test_data_branch_updates_progress_even_without_response(self, sm: MagicMock) -> None:
        # new_data is truthy but there is no "response" text: update_progress must
        # STILL fire (the `response_text or new_data` guard). Flipping to `and`
        # would skip it because response_text == "".
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        chunk = _data_chunk({"weather_data": {"t": 1}})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        sm.update_progress.assert_awaited_once()
        assert sm.update_progress.await_args.kwargs["message_chunk"] == ""

    @patch("app.utils.stream_utils.stream_manager")
    async def test_todo_progress_republished_in_data_branch(self, sm: MagicMock) -> None:
        # When a chunk carries BOTH tool data and todo_progress, the data branch
        # republishes the todo_progress snapshot as its own SSE chunk.
        sm.publish_chunk = AsyncMock()
        sm.update_progress = AsyncMock()
        st = _fresh_state()
        snapshot = {"source": "executor", "done": 4}
        chunk = _data_chunk({"weather_data": {"t": 1}, "todo_progress": snapshot})

        await process_data_chunk(
            STREAM_ID, chunk, st["tool_data"], st["tool_outputs"], st["todo_progress"], []
        )

        published = [c.args[1] for c in sm.publish_chunk.await_args_list]
        assert f"data: {json.dumps({'todo_progress': snapshot})}\n\n" in published


# ---------------------------------------------------------------------------
# set_stream_log_context
# ---------------------------------------------------------------------------


def _body(**overrides: Any) -> MessageRequestWithHistory:
    base: dict[str, Any] = {
        "message": "hi",
        "messages": [{"role": "user", "content": "hello world"}],
    }
    base.update(overrides)
    return MessageRequestWithHistory(**base)


@pytest.mark.unit
class TestSetStreamLogContext:
    @patch("app.utils.stream_utils.log")
    def test_user_id_present_sets_str_id(self, mock_log: MagicMock) -> None:
        set_stream_log_context(_body(), "user-1", "conv-1", STREAM_ID, True)
        kw = mock_log.set.call_args.kwargs
        assert kw["user"] == {"id": "user-1"}
        assert kw["chat"]["conversation_id"] == "conv-1"
        assert kw["chat"]["stream_id"] == STREAM_ID
        assert kw["chat"]["is_new_conversation"] is True

    @patch("app.utils.stream_utils.log")
    def test_user_id_none_sets_empty_dict(self, mock_log: MagicMock) -> None:
        set_stream_log_context(_body(), None, "conv", STREAM_ID, False)
        assert mock_log.set.call_args.kwargs["user"] == {}

    @patch("app.utils.stream_utils.log")
    def test_message_count_and_length(self, mock_log: MagicMock) -> None:
        body = _body(
            messages=[
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "final msg"},
            ]
        )
        set_stream_log_context(body, "u", "c", STREAM_ID, False)
        kw = mock_log.set.call_args.kwargs
        assert kw["chat"]["message_count"] == 3
        assert kw["user_message_length"] == len("final msg")

    @patch("app.utils.stream_utils.log")
    def test_empty_messages_zero_count_and_length(self, mock_log: MagicMock) -> None:
        # The `... if body.messages else 0` fallbacks: empty history -> 0, not 1.
        set_stream_log_context(_body(messages=[]), "u", "c", STREAM_ID, False)
        kw = mock_log.set.call_args.kwargs
        assert kw["chat"]["message_count"] == 0
        assert kw["user_message_length"] == 0

    @patch("app.utils.stream_utils.log")
    def test_files_reflected(self, mock_log: MagicMock) -> None:
        body = _body(
            fileIds=["f1", "f2"],
            fileData=[{"fileId": "x", "url": "u", "filename": "n"}],
        )
        set_stream_log_context(body, "u", "c", STREAM_ID, False)
        chat = mock_log.set.call_args.kwargs["chat"]
        assert chat["has_files"] is True
        assert chat["file_count"] == 3

    @patch("app.utils.stream_utils.log")
    def test_only_file_data_still_counts_as_has_files(self, mock_log: MagicMock) -> None:
        # has_files = bool(fileIds OR fileData): one source present is enough.
        # Flipping `or` to `and` would make this False (fileIds is empty).
        body = _body(fileData=[{"fileId": "x", "url": "u", "filename": "n"}])
        set_stream_log_context(body, "u", "c", STREAM_ID, False)
        chat = mock_log.set.call_args.kwargs["chat"]
        assert chat["has_files"] is True
        assert chat["file_count"] == 1

    @patch("app.utils.stream_utils.log")
    def test_no_files(self, mock_log: MagicMock) -> None:
        set_stream_log_context(_body(), "u", "c", STREAM_ID, False)
        chat = mock_log.set.call_args.kwargs["chat"]
        assert chat["has_files"] is False
        assert chat["file_count"] == 0

    @patch("app.utils.stream_utils.log")
    def test_reply_and_workflow_and_calendar(self, mock_log: MagicMock) -> None:
        body = _body(
            replyToMessage=ReplyToMessageData(id="r", content="c", role="user"),
            selectedWorkflow=SelectedWorkflowData(id="wf-9", title="t", description="d", steps=[]),
            selectedCalendarEvent=SelectedCalendarEventData(
                id="e", summary="s", description="d", start={"x": None}, end={"y": None}
            ),
            toolCategory="email",
            selectedTool="send_email",
        )
        set_stream_log_context(body, "u", "c", STREAM_ID, False)
        kw = mock_log.set.call_args.kwargs
        chat = kw["chat"]
        assert chat["has_reply"] is True
        assert chat["has_calendar_event"] is True
        assert chat["selected_workflow_id"] == "wf-9"
        assert chat["tool_category"] == "email"
        assert kw["selected_tool"] == "send_email"

    @patch("app.utils.stream_utils.log")
    def test_defaults_when_optionals_absent(self, mock_log: MagicMock) -> None:
        set_stream_log_context(_body(), "u", "c", STREAM_ID, False)
        chat = mock_log.set.call_args.kwargs["chat"]
        assert chat["has_reply"] is False
        assert chat["has_calendar_event"] is False
        assert chat["selected_workflow_id"] == ""
        assert chat["tool_category"] == ""


# ---------------------------------------------------------------------------
# aggregate_usage_metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAggregateUsageMetadata:
    def test_sums_across_entries(self) -> None:
        usage = {
            "modelA": {"input_tokens": 10, "output_tokens": 5},
            "modelB": {"input_tokens": 7, "output_tokens": 3},
        }
        assert aggregate_usage_metadata(usage) == (17, 8, 0)

    def test_non_dict_entries_skipped(self) -> None:
        usage = {"a": {"input_tokens": 4, "output_tokens": 1}, "b": "garbage", "c": None}
        assert aggregate_usage_metadata(usage) == (4, 1, 0)

    def test_cache_read_from_input_token_details(self) -> None:
        usage = {"m": {"input_tokens": 1, "input_token_details": {"cache_read": 9}}}
        assert aggregate_usage_metadata(usage) == (1, 0, 9)

    def test_cached_content_token_count_fallback(self) -> None:
        usage = {"m": {"output_tokens": 2, "cached_content_token_count": 6}}
        assert aggregate_usage_metadata(usage) == (0, 2, 6)

    def test_missing_values_coerce_to_zero(self) -> None:
        usage = {"m": {"input_tokens": None}}
        assert aggregate_usage_metadata(usage) == (0, 0, 0)


# ---------------------------------------------------------------------------
# merge_tool_outputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeToolOutputs:
    def test_matching_tool_calls_data_enriched(self) -> None:
        tool_data = {
            "tool_data": [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "t1"}}]
        }
        merge_tool_outputs(tool_data, {"t1": "OUT"})
        assert tool_data["tool_data"][0]["data"]["output"] == "OUT"

    def test_non_tool_calls_data_untouched(self) -> None:
        tool_data = {"tool_data": [{"tool_name": "weather_data", "data": {"tool_call_id": "t1"}}]}
        merge_tool_outputs(tool_data, {"t1": "OUT"})
        assert "output" not in tool_data["tool_data"][0]["data"]

    def test_unmatched_id_untouched(self) -> None:
        tool_data = {
            "tool_data": [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "t1"}}]
        }
        merge_tool_outputs(tool_data, {"other": "OUT"})
        assert "output" not in tool_data["tool_data"][0]["data"]


# ---------------------------------------------------------------------------
# inject_todo_progress
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInjectTodoProgress:
    def test_non_empty_appends_entry(self) -> None:
        tool_data: dict[str, Any] = {"tool_data": []}
        inject_todo_progress(tool_data, {"executor": {"done": 3}})
        assert len(tool_data["tool_data"]) == 1
        entry = tool_data["tool_data"][0]
        assert entry["tool_name"] == "todo_progress"
        assert entry["data"] == {"executor": {"done": 3}}
        # the entry carries a real ISO timestamp under the "timestamp" key
        datetime.fromisoformat(entry["timestamp"])

    def test_empty_appends_nothing(self) -> None:
        tool_data: dict[str, Any] = {"tool_data": []}
        inject_todo_progress(tool_data, {})
        assert tool_data["tool_data"] == []


# ---------------------------------------------------------------------------
# recover_stream_state
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecoverStreamState:
    @patch("app.utils.stream_utils.stream_manager")
    async def test_non_empty_message_short_circuits(self, sm: MagicMock) -> None:
        sm.get_progress = AsyncMock()
        msg, _ = await recover_stream_state(STREAM_ID, "already here", {"tool_data": []})
        assert msg == "already here"
        sm.get_progress.assert_not_awaited()

    @patch("app.utils.stream_utils.stream_manager")
    async def test_no_progress_returns_inputs(self, sm: MagicMock) -> None:
        sm.get_progress = AsyncMock(return_value=None)
        td_in: dict[str, Any] = {"tool_data": []}
        msg, td = await recover_stream_state(STREAM_ID, "", td_in)
        assert msg == ""
        assert td is td_in

    @patch("app.utils.stream_utils.stream_manager")
    async def test_recovers_message_from_progress(self, sm: MagicMock) -> None:
        sm.get_progress = AsyncMock(return_value={"complete_message": "from-redis"})
        msg, _ = await recover_stream_state(STREAM_ID, "", {"tool_data": []})
        assert msg == "from-redis"

    @patch("app.utils.stream_utils.stream_manager")
    async def test_progress_tool_data_replaces_empty_local(self, sm: MagicMock) -> None:
        progress_td = {"tool_data": [{"tool_name": "x"}]}
        sm.get_progress = AsyncMock(
            return_value={"complete_message": "m", "tool_data": progress_td}
        )
        _, td = await recover_stream_state(STREAM_ID, "", {"tool_data": []})
        assert td is progress_td

    @patch("app.utils.stream_utils.stream_manager")
    async def test_existing_local_tool_data_preserved(self, sm: MagicMock) -> None:
        local = {"tool_data": [{"tool_name": "local"}]}
        sm.get_progress = AsyncMock(
            return_value={"complete_message": "m", "tool_data": {"tool_data": [{"x": 1}]}}
        )
        _, td = await recover_stream_state(STREAM_ID, "", local)
        assert td is local


# ---------------------------------------------------------------------------
# publish_description_if_ready
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPublishDescriptionIfReady:
    @patch("app.utils.stream_utils.stream_manager")
    async def test_none_task_returns_none(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        assert await publish_description_if_ready(STREAM_ID, None) is None
        sm.publish_chunk.assert_not_awaited()

    @patch("app.utils.stream_utils.stream_manager")
    async def test_not_done_task_returned_unchanged(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        task = MagicMock()
        task.done.return_value = False
        assert await publish_description_if_ready(STREAM_ID, task) is task
        sm.publish_chunk.assert_not_awaited()

    @patch("app.utils.stream_utils.stream_manager")
    async def test_done_task_publishes_description(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        task = MagicMock()
        task.done.return_value = True
        task.result.return_value = "My Conversation"

        result = await publish_description_if_ready(STREAM_ID, task)

        assert result is None
        # Exact SSE wire format: "data: " prefix + keyed payload + "\n\n".
        published = sm.publish_chunk.await_args.args[1]
        expected = f"data: {json.dumps({'conversation_description': 'My Conversation'})}\n\n"
        assert published == expected

    @patch("app.utils.stream_utils.stream_manager")
    async def test_failing_task_swallowed(self, sm: MagicMock) -> None:
        sm.publish_chunk = AsyncMock()
        task = MagicMock()
        task.done.return_value = True
        task.result.side_effect = RuntimeError("boom")

        result = await publish_description_if_ready(STREAM_ID, task)

        assert result is None
        sm.publish_chunk.assert_not_awaited()


# ---------------------------------------------------------------------------
# absorb_collector_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAbsorbCollectorEvent:
    def test_tool_data_appended(self) -> None:
        acc: dict[str, Any] = {"tool_data": []}
        absorb_collector_event({"tool_data": {"tool_name": "x"}}, acc, {})
        assert acc["tool_data"] == [{"tool_name": "x"}]

    def test_tool_output_with_id_captured(self) -> None:
        outputs: dict[str, str] = {}
        absorb_collector_event(
            {"tool_output": {"tool_call_id": "t1", "output": "v"}}, {"tool_data": []}, outputs
        )
        assert outputs == {"t1": "v"}

    def test_tool_output_missing_fields_not_captured(self) -> None:
        outputs: dict[str, str] = {}
        absorb_collector_event({"tool_output": {"output": "v"}}, {"tool_data": []}, outputs)
        assert outputs == {}

    def test_subagent_start_and_end_routed(self) -> None:
        acc: dict[str, Any] = {"tool_data": []}
        absorb_collector_event({"subagent_start": {"subagent_id": "s1", "n": 1}}, acc, {})
        absorb_collector_event({"subagent_end": {"subagent_id": "s1", "d": 2}}, acc, {})
        assert acc["subagent_starts"]["s1"] == {"subagent_id": "s1", "n": 1}
        assert acc["subagent_ends"]["s1"] == {"subagent_id": "s1", "d": 2}


# ---------------------------------------------------------------------------
# apply_outputs_to_tool_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyOutputsToToolData:
    def test_matching_entry_enriched_no_filter(self) -> None:
        entries = [{"tool_name": "weather_data", "data": {"tool_call_id": "t1"}}]
        apply_outputs_to_tool_data(entries, {"t1": "OUT"})
        assert entries[0]["data"]["output"] == "OUT"

    def test_only_tool_name_filters(self) -> None:
        entries = [
            {"tool_name": "weather_data", "data": {"tool_call_id": "t1"}},
            {"tool_name": "tool_calls_data", "data": {"tool_call_id": "t2"}},
        ]
        apply_outputs_to_tool_data(
            entries, {"t1": "A", "t2": "B"}, only_tool_name="tool_calls_data"
        )
        assert "output" not in entries[0]["data"]
        assert entries[1]["data"]["output"] == "B"

    def test_non_dict_data_skipped(self) -> None:
        entries: list[dict[str, Any]] = [{"tool_name": "x", "data": "not-a-dict"}]
        apply_outputs_to_tool_data(entries, {"t1": "OUT"})
        assert entries[0]["data"] == "not-a-dict"

    def test_unmatched_id_untouched(self) -> None:
        entries = [{"tool_name": "x", "data": {"tool_call_id": "t1"}}]
        apply_outputs_to_tool_data(entries, {"other": "OUT"})
        assert "output" not in entries[0]["data"]


# ---------------------------------------------------------------------------
# reconstruct_subagent_groups
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReconstructSubagentGroups:
    def test_no_starts_pops_keys_and_keeps_tool_data(self) -> None:
        tool_data: dict[str, Any] = {
            "tool_data": [{"tool_name": "weather_data"}],
            "subagent_starts": {},
            "subagent_ends": {},
        }
        reconstruct_subagent_groups(tool_data)
        assert tool_data["tool_data"] == [{"tool_name": "weather_data"}]
        assert "subagent_starts" not in tool_data
        assert "subagent_ends" not in tool_data

    def test_tagged_tool_call_routed_into_group_full_shape(self) -> None:
        tool_data: dict[str, Any] = {
            "tool_data": [
                {
                    "tool_name": "tool_calls_data",
                    "subagent_id": "s1",
                    "data": {"tool_call_id": "tc"},
                },
            ],
            "subagent_starts": {
                "s1": {
                    "subagent_name": "Worker",
                    "agent_type": "handoff",
                    "started_at": "2020-01-01T00:00:00+00:00",
                    "icon_url": "https://i/w.png",
                    "tool_category": "email",
                }
            },
            "subagent_ends": {"s1": {"duration_ms": 50, "token_count": 100}},
        }
        reconstruct_subagent_groups(tool_data)

        groups = [e for e in tool_data["tool_data"] if e["tool_name"] == "subagent_group"]
        assert len(groups) == 1
        wrapper = groups[0]
        group = wrapper["data"]
        # full persisted shape — every key/value mapped from start/end
        assert group["subagent_id"] == "s1"
        assert group["subagent_name"] == "Worker"
        assert group["agent_type"] == "handoff"
        assert group["duration_ms"] == 50
        assert group["token_count"] == 100
        assert group["started_at"] == "2020-01-01T00:00:00+00:00"
        assert group["icon_url"] == "https://i/w.png"
        assert group["tool_category"] == "email"
        assert group["tool_calls"] == [{"tool_call_id": "tc"}]
        assert group["completed_at"] is not None
        # wrapper timestamp mirrors the group's started_at
        assert wrapper["timestamp"] == "2020-01-01T00:00:00+00:00"

    def test_agent_type_defaults_to_spawned(self) -> None:
        # start event omits agent_type -> the "spawned" default literal is used.
        tool_data: dict[str, Any] = {
            "tool_data": [],
            "subagent_starts": {"s1": {"subagent_name": "W"}},
            "subagent_ends": {},
        }
        reconstruct_subagent_groups(tool_data)
        group = tool_data["tool_data"][0]["data"]
        assert group["agent_type"] == "spawned"

    def test_entry_with_unknown_tool_name_stays_top_level(self) -> None:
        # An entry tagged with a known subagent_id but whose tool_name is NOT
        # "tool_calls_data" must remain top-level (the trailing `and tool_name ==`).
        tool_data: dict[str, Any] = {
            "tool_data": [
                {"tool_name": "weather_data", "subagent_id": "s1", "data": {"id": "w"}},
            ],
            "subagent_starts": {"s1": {"subagent_name": "W"}},
            "subagent_ends": {},
        }
        reconstruct_subagent_groups(tool_data)

        top = [e for e in tool_data["tool_data"] if e["tool_name"] == "weather_data"]
        assert top == [{"tool_name": "weather_data", "subagent_id": "s1", "data": {"id": "w"}}]
        group = next(e for e in tool_data["tool_data"] if e["tool_name"] == "subagent_group")
        # the entry was NOT routed into the group
        assert group["data"]["tool_calls"] == []

    def test_untagged_entry_stays_top_level_and_no_end_means_no_completed_at(self) -> None:
        tool_data: dict[str, Any] = {
            "tool_data": [
                {"tool_name": "weather_data", "data": {}},
                {"tool_name": "tool_calls_data", "subagent_id": "s1", "data": {"id": "tc"}},
            ],
            "subagent_starts": {"s1": {"subagent_name": "W"}},
            "subagent_ends": {},
        }
        reconstruct_subagent_groups(tool_data)

        names = [e["tool_name"] for e in tool_data["tool_data"]]
        # weather_data stays top-level, subagent_group appended
        assert names[0] == "weather_data"
        assert "subagent_group" in names
        group = next(e for e in tool_data["tool_data"] if e["tool_name"] == "subagent_group")
        # no end event -> completed_at is None
        assert group["data"]["completed_at"] is None
        # the s1-tagged tool_calls_data entry WAS routed in
        assert group["data"]["tool_calls"] == [{"id": "tc"}]

    def test_orphan_parent_id_keeps_group_at_root(self) -> None:
        # parent_subagent_id points at a non-existent parent: the group stays at
        # root (the `parent_id and parent_id in groups` guard). Flipping `and` to
        # `or` would attempt groups[parent_id] and raise KeyError.
        tool_data: dict[str, Any] = {
            "tool_data": [],
            "subagent_starts": {"s1": {"subagent_name": "Lonely", "parent_subagent_id": "ghost"}},
            "subagent_ends": {},
        }
        reconstruct_subagent_groups(tool_data)

        groups = [e for e in tool_data["tool_data"] if e["tool_name"] == "subagent_group"]
        assert len(groups) == 1
        assert groups[0]["data"]["subagent_name"] == "Lonely"

    def test_child_group_nested_under_parent(self) -> None:
        tool_data: dict[str, Any] = {
            "tool_data": [],
            "subagent_starts": {
                "parent": {"subagent_name": "Parent"},
                "child": {"subagent_name": "Child", "parent_subagent_id": "parent"},
            },
            "subagent_ends": {},
        }
        reconstruct_subagent_groups(tool_data)

        groups = [e for e in tool_data["tool_data"] if e["tool_name"] == "subagent_group"]
        # only the parent is emitted at root; child is nested inside it
        assert len(groups) == 1
        parent = groups[0]["data"]
        assert parent["subagent_name"] == "Parent"
        nested_names = [g["subagent_name"] for g in parent["nested_subagents"]]
        assert nested_names == ["Child"]
