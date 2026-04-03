"""
Service tests: call real run_chat_stream_background() with real Redis + MongoDB.

Only mock: call_agent (returns fake LLM stream).
Real: stream_manager (real Redis), _save_conversation_async -> update_messages
(real MongoDB), all chunk processing, tool merging, cleanup.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.models.message_models import MessageRequestWithHistory
from app.services.chat_service import run_chat_stream_background


def _fake_stream(*chunks):
    """Build a fake agent async generator from chunk strings."""

    async def _gen():
        for c in chunks:
            yield c

    return _gen


def _make_usage_mock():
    """Build a UsageMetadataCallbackHandler mock that returns a real dict for metadata."""
    mock_cls = MagicMock()
    instance = MagicMock()
    instance.usage_metadata = {}
    mock_cls.return_value = instance
    return mock_cls


@pytest.mark.service
class TestChatPipelineReal:
    """Full pipeline: run_chat_stream_background with real Redis + MongoDB."""

    async def test_messages_saved_to_mongodb(
        self, real_redis, conversations_collection, make_conversation
    ):
        """After streaming, user+bot messages must exist in real MongoDB."""
        conv_id = await make_conversation("pipe-user-1")

        body = MessageRequestWithHistory(
            message="What is 2+2?",
            messages=[{"role": "user", "content": "What is 2+2?"}],
            conversation_id=conv_id,
        )

        agent_stream = _fake_stream(
            'data: {"response": "The answer is 4."}\n\n',
            f"nostream: {json.dumps({'complete_message': 'The answer is 4.'})}",
            "data: [DONE]\n\n",
        )

        with (
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_stream()),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=f"stream_{ObjectId()}",
                body=body,
                user={"user_id": "pipe-user-1"},
                user_time=datetime.now(timezone.utc),
                conversation_id=conv_id,
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert doc is not None
        assert len(doc["messages"]) == 2
        assert doc["messages"][0]["type"] == "user"
        assert doc["messages"][0]["response"] == "What is 2+2?"
        assert doc["messages"][1]["type"] == "bot"
        assert doc["messages"][1]["response"] == "The answer is 4."

    async def test_redis_cleaned_up_after_stream(
        self, real_redis, conversations_collection, make_conversation
    ):
        """After streaming, Redis progress and signal keys must be deleted."""
        from app.core.stream_manager import StreamManager

        conv_id = await make_conversation("pipe-user-3")
        stream_id = f"stream_{ObjectId()}"

        body = MessageRequestWithHistory(
            message="Hello",
            messages=[{"role": "user", "content": "Hello"}],
            conversation_id=conv_id,
        )

        agent_stream = _fake_stream(
            f"nostream: {json.dumps({'complete_message': 'Hi'})}",
            "data: [DONE]\n\n",
        )

        with (
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_stream()),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=stream_id,
                body=body,
                user={"user_id": "pipe-user-3"},
                user_time=datetime.now(timezone.utc),
                conversation_id=conv_id,
            )

        assert await StreamManager.get_progress(stream_id) is None

    async def test_agent_failure_still_saves_and_cleans_up(
        self, real_redis, conversations_collection, make_conversation
    ):
        """If call_agent raises, conversation must still be saved and Redis cleaned."""
        from app.core.stream_manager import StreamManager

        conv_id = await make_conversation("pipe-user-4")
        stream_id = f"stream_{ObjectId()}"

        body = MessageRequestWithHistory(
            message="Crash me",
            messages=[{"role": "user", "content": "Crash me"}],
            conversation_id=conv_id,
        )

        with (
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(side_effect=RuntimeError("agent exploded")),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=stream_id,
                body=body,
                user={"user_id": "pipe-user-4"},
                user_time=datetime.now(timezone.utc),
                conversation_id=conv_id,
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert doc is not None
        assert len(doc["messages"]) == 2

        assert await StreamManager.get_progress(stream_id) is None
