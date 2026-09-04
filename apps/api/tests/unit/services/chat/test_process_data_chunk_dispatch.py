"""The ``data:`` chunk dispatcher forwards each event to the right publisher
with the turn's own stream id and accumulators.

A wrong stream id would publish a user's tool cards into someone else's
stream, and a dropped accumulator would lose the cards from the saved turn,
so every publisher call is pinned argument by argument here.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from app.services.chat.chunks import ChunkAccumulators, process_data_chunk

MODULE = "app.services.chat.chunks"
STREAM = "stream-77"


def _acc() -> ChunkAccumulators:
    return ChunkAccumulators(
        tool_data={"tool_data": []},
        tool_outputs={},
        todo_progress={},
        follow_up_actions=["earlier chip"],
    )


def _chunk(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class TestSubagentLifecycleForwarding:
    async def test_lifecycle_frames_go_to_the_turn_stream_with_its_tool_data(self) -> None:
        acc = _acc()
        payload = {"subagent_start": {"subagent_id": "sa-1"}}
        lifecycle = AsyncMock(return_value=True)
        publish_chunk = AsyncMock()
        with (
            patch(f"{MODULE}._forward_subagent_lifecycle", lifecycle),
            patch(f"{MODULE}._settle_boundary", AsyncMock()),
            patch(f"{MODULE}.stream_manager.publish_chunk", publish_chunk),
        ):
            result = await process_data_chunk(STREAM, _chunk(payload), acc, forward_subagents=True)

        lifecycle.assert_awaited_once_with(STREAM, payload, acc.tool_data)
        assert result == (["earlier chip"], True)
        # Already published as dedicated frames: the raw chunk must not go out twice.
        publish_chunk.assert_not_awaited()

    async def test_without_forwarding_the_lifecycle_helper_is_never_consulted(self) -> None:
        acc = _acc()
        payload = {"subagent_start": {"subagent_id": "sa-1"}}
        lifecycle = AsyncMock(return_value=True)
        publish_chunk = AsyncMock()
        with (
            patch(f"{MODULE}._forward_subagent_lifecycle", lifecycle),
            patch(f"{MODULE}._settle_boundary", AsyncMock()),
            patch(f"{MODULE}.stream_manager.publish_chunk", publish_chunk),
            patch(f"{MODULE}.stream_manager.update_progress", AsyncMock()),
        ):
            result = await process_data_chunk(STREAM, _chunk(payload), acc)

        lifecycle.assert_not_awaited()
        publish_chunk.assert_awaited_once_with(STREAM, _chunk(payload))
        assert result == (["earlier chip"], True)


class TestToolDataDispatch:
    async def test_every_publisher_gets_the_turn_stream_and_its_own_accumulator(self) -> None:
        acc = _acc()
        payload = {"follow_up_actions": ["Draft the reply", "Book the slot"]}
        # extract_tool_data files non-tool keys under other_data before publishing.
        new_data = {"other_data": payload}
        other = AsyncMock(return_value=["Draft the reply", "Book the slot"])
        tool_data = AsyncMock()
        tool_output = AsyncMock()
        with (
            patch(f"{MODULE}._settle_boundary", AsyncMock()),
            patch(f"{MODULE}.publish_other_data", other),
            patch(f"{MODULE}.publish_tool_data", tool_data),
            patch(f"{MODULE}.publish_tool_output", tool_output),
            patch(f"{MODULE}.stream_manager.update_progress", AsyncMock()),
        ):
            result = await process_data_chunk(STREAM, _chunk(payload), acc)

        other.assert_awaited_once_with(STREAM, new_data, ["earlier chip"])
        tool_data.assert_awaited_once_with(STREAM, new_data, acc.tool_data)
        tool_output.assert_awaited_once_with(STREAM, new_data, acc.tool_outputs)
        assert result == (["Draft the reply", "Book the slot"], True)
        assert acc.follow_up_actions == ["Draft the reply", "Book the slot"]
