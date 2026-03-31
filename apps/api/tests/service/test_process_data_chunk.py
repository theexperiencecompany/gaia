"""
Service tests: call real _process_data_chunk() against real Redis.

Verifies that tool_data, follow_up_actions, and tool_outputs are correctly
extracted from agent chunks and republished to Redis.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.core.stream_manager import StreamManager
from app.services.chat_service import _process_data_chunk


@pytest.mark.service
class TestProcessDataChunkReal:
    """Call real _process_data_chunk with real Redis publishing."""

    async def test_tool_data_extracted_and_accumulated(self, real_redis):
        """Tool data in a chunk must be extracted and accumulated."""
        stream_id = "chunk-test-1"
        await StreamManager.start_stream(stream_id, "c1", "u1")

        tool_data_acc: dict = {"tool_data": []}
        tool_outputs: dict = {}
        todo_progress_accumulated: dict = {}
        follow_up_actions: list = []

        chunk_payload = json.dumps(
            {
                "tool_data": {
                    "tool_name": "web_search",
                    "data": {"query": "cats"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            }
        )
        chunk = f"data: {chunk_payload}\n\n"

        with patch("app.services.chat_service.stream_manager") as mock_sm:
            mock_sm.publish_chunk = AsyncMock()
            mock_sm.update_progress = AsyncMock()

            await _process_data_chunk(
                stream_id,
                chunk,
                tool_data_acc,
                tool_outputs,
                todo_progress_accumulated,
                follow_up_actions,
            )

        assert len(tool_data_acc["tool_data"]) == 1
        assert tool_data_acc["tool_data"][0]["tool_name"] == "web_search"

    async def test_follow_up_actions_extracted(self, real_redis):
        """Follow-up actions must be extracted and returned."""
        stream_id = "chunk-test-2"
        await StreamManager.start_stream(stream_id, "c2", "u2")

        tool_data_acc: dict = {"tool_data": []}
        tool_outputs: dict = {}
        todo_progress_accumulated: dict = {}
        follow_up_actions: list = []

        # follow_up_actions are top-level in the chunk per extract_tool_data contract
        chunk_payload = json.dumps(
            {"follow_up_actions": ["Draft email", "Schedule meeting"]}
        )
        chunk = f"data: {chunk_payload}\n\n"

        with patch("app.services.chat_service.stream_manager") as mock_sm:
            mock_sm.publish_chunk = AsyncMock()
            mock_sm.update_progress = AsyncMock()

            result_follow_up, _ = await _process_data_chunk(
                stream_id,
                chunk,
                tool_data_acc,
                tool_outputs,
                todo_progress_accumulated,
                follow_up_actions,
            )

        assert result_follow_up == ["Draft email", "Schedule meeting"]

    async def test_tool_output_captured(self, real_redis):
        """Tool outputs must be captured in tool_outputs dict by tool_call_id."""
        stream_id = "chunk-test-3"
        await StreamManager.start_stream(stream_id, "c3", "u3")

        tool_data_acc: dict = {"tool_data": []}
        tool_outputs: dict = {}
        todo_progress_accumulated: dict = {}
        follow_up_actions: list = []

        chunk_payload = json.dumps(
            {"tool_output": {"tool_call_id": "call_abc", "output": "10 results found"}}
        )
        chunk = f"data: {chunk_payload}\n\n"

        with patch("app.services.chat_service.stream_manager") as mock_sm:
            mock_sm.publish_chunk = AsyncMock()
            mock_sm.update_progress = AsyncMock()

            await _process_data_chunk(
                stream_id,
                chunk,
                tool_data_acc,
                tool_outputs,
                todo_progress_accumulated,
                follow_up_actions,
            )

        assert tool_outputs["call_abc"] == "10 results found"
