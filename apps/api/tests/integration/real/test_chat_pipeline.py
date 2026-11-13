"""
Service tests: call real run_chat_stream_background() with real Redis + MongoDB.

Only mock: call_agent (returns fake LLM stream).
Real: stream_manager (real Redis), save_user_message / save_bot_reply -> update_messages
(real MongoDB), all chunk processing, tool merging, cleanup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from unittest.mock import MagicMock, patch

from bson import ObjectId
import pytest

from app.constants import chat as chat_constants
from app.models.message_models import MessageRequestWithHistory
from app.services.chat.stream import run_chat_stream_background
from tests.factories import make_authenticated_user


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
                "app.services.chat.stream.call_agent",
                new=MagicMock(return_value=agent_stream()),
            ),
            patch(
                "app.services.chat.stream.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=f"stream_{ObjectId()}",
                body=body,
                user=make_authenticated_user(user_id="pipe-user-1"),
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
                "app.services.chat.stream.call_agent",
                new=MagicMock(return_value=agent_stream()),
            ),
            patch(
                "app.services.chat.stream.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=stream_id,
                body=body,
                user=make_authenticated_user(user_id="pipe-user-3"),
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
                "app.services.chat.stream.call_agent",
                new=MagicMock(side_effect=RuntimeError("agent exploded")),
            ),
            patch(
                "app.services.chat.stream.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=stream_id,
                body=body,
                user=make_authenticated_user(user_id="pipe-user-4"),
                conversation_id=conv_id,
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert doc is not None
        assert len(doc["messages"]) == 2

        assert await StreamManager.get_progress(stream_id) is None

    @pytest.mark.regression
    async def test_the_users_message_is_saved_before_the_agent_runs(
        self, real_redis, conversations_collection, make_conversation
    ):
        """Regression: a turn killed mid-run (deploy, OOM) kept its side effects but no messages."""
        conv_id = await make_conversation("pipe-user-5")
        body = MessageRequestWithHistory(
            message="remind me to stretch",
            messages=[{"role": "user", "content": "remind me to stretch"}],
            conversation_id=conv_id,
        )
        seen_while_running: list[dict[str, object]] = []

        async def _agent_that_reads_mongo() -> AsyncIterator[str]:
            doc = await conversations_collection.find_one({"conversation_id": conv_id})
            seen_while_running.extend(doc["messages"])
            yield f"nostream: {json.dumps({'complete_message': 'Done.'})}"

        with (
            patch(
                "app.services.chat.stream.call_agent",
                new=MagicMock(return_value=_agent_that_reads_mongo()),
            ),
            patch(
                "app.services.chat.stream.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=f"stream_{ObjectId()}",
                body=body,
                user=make_authenticated_user(user_id="pipe-user-5"),
                conversation_id=conv_id,
            )

        assert [(m["type"], m["response"]) for m in seen_while_running] == [
            ("user", "remind me to stretch")
        ]
        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert [(m["type"], m["response"]) for m in doc["messages"]] == [
            ("user", "remind me to stretch"),
            ("bot", "Done."),
        ]

    @pytest.mark.regression
    async def test_a_reply_that_cannot_be_saved_leaves_the_turn_with_a_visible_error(
        self, real_redis, conversations_collection, make_conversation
    ):
        """Regression: a failed reply write discarded the whole turn, user message included."""
        conv_id = await make_conversation("pipe-user-6")
        body = MessageRequestWithHistory(
            message="remind me to stretch",
            messages=[{"role": "user", "content": "remind me to stretch"}],
            conversation_id=conv_id,
        )
        # A card past Mongo's 16MB document cap, so the reply write itself fails.
        oversized_card = {
            "tool_data": {
                "tool_name": "tool_calls_data",
                "data": {"tool_name": "x", "tool_call_id": "c1", "output": "x" * 17_000_000},
            }
        }
        agent_stream = _fake_stream(
            f"data: {json.dumps(oversized_card)}\n\n",
            f"nostream: {json.dumps({'complete_message': 'Reminder set.'})}",
        )

        with (
            patch(
                "app.services.chat.stream.call_agent",
                new=MagicMock(return_value=agent_stream()),
            ),
            patch(
                "app.services.chat.stream.UsageMetadataCallbackHandler",
                _make_usage_mock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id=f"stream_{ObjectId()}",
                body=body,
                user=make_authenticated_user(user_id="pipe-user-6"),
                conversation_id=conv_id,
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert [(m["type"], m["response"]) for m in doc["messages"]] == [
            ("user", "remind me to stretch"),
            ("bot", ""),
        ]
        assert doc["messages"][1]["error"] == getattr(chat_constants, "TURN_REPLY_NOT_SAVED", None)
