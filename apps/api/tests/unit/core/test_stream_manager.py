"""Tests for StreamManager — Redis Pub/Sub stream lifecycle.

Covers: start, complete, cleanup, publish, subscribe (all signal types
and edge cases), cancel, is_cancelled, progress tracking, and error recording.
"""

import json
from dataclasses import asdict
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.cache import (
    STREAM_CHANNEL_PREFIX,
    STREAM_PROGRESS_PREFIX,
    STREAM_SIGNAL_PREFIX,
    STREAM_TTL,
)
from app.constants.streaming import (
    STREAM_CANCELLED_SIGNAL,
    STREAM_DONE_SIGNAL,
    STREAM_ERROR_SIGNAL,
)
from app.core.stream_manager import StreamManager, StreamProgress


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _progress_dict(
    conversation_id: str = "conv-1",
    user_id: str = "user-1",
    complete_message: str = "",
    tool_data: Optional[Dict[str, Any]] = None,
    is_cancelled: bool = False,
    is_complete: bool = False,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a dict that mirrors what Redis stores for StreamProgress."""
    return {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "complete_message": complete_message,
        "tool_data": tool_data or {},
        "started_at": "2026-01-01T00:00:00+00:00",
        "is_cancelled": is_cancelled,
        "is_complete": is_complete,
        "error": error,
    }


class _FakePubSub:
    """Lightweight stand-in for redis.asyncio pubsub objects."""

    def __init__(self, messages: Optional[List[Optional[Dict[str, Any]]]] = None):
        self._messages = list(messages or [])
        self._idx = 0
        self.subscribe = AsyncMock()
        self.unsubscribe = AsyncMock()
        self.aclose = AsyncMock()

    async def get_message(
        self, ignore_subscribe_messages: bool = True, timeout: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        if self._idx >= len(self._messages):
            return None
        msg = self._messages[self._idx]
        self._idx += 1
        return msg


# ---------------------------------------------------------------------------
# StreamProgress dataclass
# ---------------------------------------------------------------------------


class TestStreamProgress:
    def test_default_fields(self) -> None:
        progress = StreamProgress(conversation_id="c1", user_id="u1")
        assert progress.complete_message == ""
        assert progress.tool_data == {}
        assert progress.is_cancelled is False
        assert progress.is_complete is False
        assert progress.error is None
        # started_at should be an ISO string
        assert "T" in progress.started_at

    def test_asdict_round_trip(self) -> None:
        progress = StreamProgress(
            conversation_id="c1",
            user_id="u1",
            complete_message="hello",
            is_complete=True,
        )
        d = asdict(progress)
        assert d["conversation_id"] == "c1"
        assert d["is_complete"] is True


# ---------------------------------------------------------------------------
# start_stream
# ---------------------------------------------------------------------------


class TestStartStream:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.mock_set = AsyncMock()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(set=self.mock_set),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_stores_progress_in_redis(self) -> None:
        await StreamManager.start_stream("s1", "conv-1", "user-1")

        self.mock_set.assert_awaited_once()
        call_args = self.mock_set.call_args
        key = call_args[0][0]
        data = call_args[0][1]
        ttl = call_args[1]["ttl"] if "ttl" in call_args[1] else call_args[0][2]

        assert key == f"{STREAM_PROGRESS_PREFIX}s1"
        assert data["conversation_id"] == "conv-1"
        assert data["user_id"] == "user-1"
        assert data["is_complete"] is False
        assert data["is_cancelled"] is False
        assert ttl == STREAM_TTL


# ---------------------------------------------------------------------------
# complete_stream
# ---------------------------------------------------------------------------


class TestCompleteStream:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.stored: Dict[str, Any] = {}
        self.mock_get = AsyncMock(return_value=_progress_dict())
        self.mock_set = AsyncMock()
        self.mock_redis_client = MagicMock()
        self.mock_redis_client.publish = AsyncMock()

        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(
                get=self.mock_get,
                set=self.mock_set,
                redis=self.mock_redis_client,
            ),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_marks_progress_complete_and_publishes_done(self) -> None:
        await StreamManager.complete_stream("s1")

        # Progress updated with is_complete=True
        set_call = self.mock_set.call_args
        data = set_call[0][1]
        assert data["is_complete"] is True

        # DONE signal published
        self.mock_redis_client.publish.assert_awaited_once_with(
            f"{STREAM_CHANNEL_PREFIX}s1",
            STREAM_DONE_SIGNAL,
        )

    async def test_publishes_done_even_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        await StreamManager.complete_stream("s1")

        # set should NOT be called when progress_data is None
        self.mock_set.assert_not_awaited()
        # but done signal should still be published
        self.mock_redis_client.publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.mock_delete = AsyncMock()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(delete=self.mock_delete),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_deletes_progress_and_signal_keys(self) -> None:
        await StreamManager.cleanup("s1")

        calls = [c[0][0] for c in self.mock_delete.call_args_list]
        assert f"{STREAM_PROGRESS_PREFIX}s1" in calls
        assert f"{STREAM_SIGNAL_PREFIX}s1" in calls


# ---------------------------------------------------------------------------
# publish_chunk
# ---------------------------------------------------------------------------


class TestPublishChunk:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.mock_redis_client = MagicMock()
        self.mock_redis_client.publish = AsyncMock()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=self.mock_redis_client),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_publishes_chunk_to_channel(self) -> None:
        await StreamManager.publish_chunk("s1", "data: hello\n\n")

        self.mock_redis_client.publish.assert_awaited_once_with(
            f"{STREAM_CHANNEL_PREFIX}s1",
            "data: hello\n\n",
        )

    async def test_noop_when_redis_unavailable(self) -> None:
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=None),
        ):
            # Should not raise
            await StreamManager.publish_chunk("s1", "data: hello\n\n")


# ---------------------------------------------------------------------------
# subscribe_stream
# ---------------------------------------------------------------------------


class TestSubscribeStream:
    def _make_msg(self, data: str) -> Dict[str, Any]:
        return {"type": "message", "data": data}

    async def test_yields_chunks_until_done(self) -> None:
        pubsub = _FakePubSub(
            [
                self._make_msg("data: chunk1\n\n"),
                self._make_msg("data: chunk2\n\n"),
                self._make_msg(STREAM_DONE_SIGNAL),
            ]
        )
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        assert chunks == ["data: chunk1\n\n", "data: chunk2\n\n"]
        pubsub.unsubscribe.assert_awaited_once()
        pubsub.aclose.assert_awaited_once()

    async def test_cancelled_signal_yields_done_marker(self) -> None:
        pubsub = _FakePubSub(
            [
                self._make_msg("data: chunk1\n\n"),
                self._make_msg(STREAM_CANCELLED_SIGNAL),
            ]
        )
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        assert chunks == ["data: chunk1\n\n", "data: [DONE]\n\n"]

    async def test_error_signal_yields_error_json(self) -> None:
        progress = _progress_dict(error="Something failed")
        mock_get = AsyncMock(return_value=progress)

        pubsub = _FakePubSub([self._make_msg(STREAM_ERROR_SIGNAL)])
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client, get=mock_get),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        assert len(chunks) == 1
        payload = json.loads(chunks[0].removeprefix("data: ").strip())
        assert payload["error"] == "Something failed"

    async def test_error_signal_with_no_progress_uses_default(self) -> None:
        mock_get = AsyncMock(return_value=None)

        pubsub = _FakePubSub([self._make_msg(STREAM_ERROR_SIGNAL)])
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client, get=mock_get),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        payload = json.loads(chunks[0].removeprefix("data: ").strip())
        assert payload["error"] == "An unexpected error occurred"

    async def test_keepalive_on_timeout(self) -> None:
        """When pubsub returns None (timeout), a keepalive data event is yielded."""
        pubsub = _FakePubSub(
            [
                None,  # timeout → keepalive
                self._make_msg(STREAM_DONE_SIGNAL),
            ]
        )
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream(
                "s1", keepalive_interval=0.01
            ):
                chunks.append(chunk)

        assert chunks == ['data: {"keepalive":true}\n\n']

    async def test_skips_non_message_types(self) -> None:
        pubsub = _FakePubSub(
            [
                {"type": "subscribe", "data": None},
                self._make_msg("data: real\n\n"),
                self._make_msg(STREAM_DONE_SIGNAL),
            ]
        )
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        assert chunks == ["data: real\n\n"]

    async def test_decodes_bytes_data(self) -> None:
        pubsub = _FakePubSub(
            [
                {"type": "message", "data": b"data: bytes_chunk\n\n"},
                self._make_msg(STREAM_DONE_SIGNAL),
            ]
        )
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        assert chunks == ["data: bytes_chunk\n\n"]

    async def test_returns_immediately_when_redis_unavailable(self) -> None:
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=None),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        assert chunks == []

    async def test_exception_during_subscription_yields_error(self) -> None:
        pubsub = _FakePubSub()
        # Make get_message raise after the first call

        call_count = 0

        async def exploding_get(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("connection lost")
            return None

        pubsub.get_message = exploding_get  # type: ignore[assignment]

        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        assert len(chunks) == 1
        payload = json.loads(chunks[0].removeprefix("data: ").strip())
        assert payload["error"] == "Stream subscription failed"

    async def test_cleanup_errors_suppressed_in_finally(self) -> None:
        """Errors during pubsub cleanup (unsubscribe/aclose) should be swallowed."""
        pubsub = _FakePubSub([self._make_msg(STREAM_DONE_SIGNAL)])
        pubsub.unsubscribe = AsyncMock(side_effect=RuntimeError("cleanup fail"))
        pubsub.aclose = AsyncMock(side_effect=RuntimeError("close fail"))

        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=mock_redis_client),
        ):
            chunks: List[str] = []
            async for chunk in StreamManager.subscribe_stream("s1"):
                chunks.append(chunk)

        # Should complete without raising
        assert chunks == []

    async def test_warning_logged_when_no_chunks_received(self) -> None:
        """When stream ends with zero data chunks, a warning should be logged."""
        pubsub = _FakePubSub([self._make_msg(STREAM_DONE_SIGNAL)])
        mock_redis_client = MagicMock()
        mock_redis_client.pubsub.return_value = pubsub

        with (
            patch(
                "app.core.stream_manager.redis_cache",
                new=MagicMock(redis=mock_redis_client),
            ),
            patch("app.core.stream_manager.log") as mock_log,
        ):
            async for _ in StreamManager.subscribe_stream("s1"):
                pass

        mock_log.warning.assert_called_once()
        assert "without receiving any chunks" in mock_log.warning.call_args[0][0]


# ---------------------------------------------------------------------------
# cancel_stream
# ---------------------------------------------------------------------------


class TestCancelStream:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.mock_set = AsyncMock()
        self.mock_get = AsyncMock(return_value=_progress_dict())
        self.mock_redis_client = MagicMock()
        self.mock_redis_client.publish = AsyncMock()

        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(
                set=self.mock_set,
                get=self.mock_get,
                redis=self.mock_redis_client,
            ),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_sets_signal_and_updates_progress(self) -> None:
        result = await StreamManager.cancel_stream("s1")
        assert result is True

        # Should have called set twice: once for signal, once for progress
        assert self.mock_set.await_count == 2

        # First call: signal
        signal_call = self.mock_set.call_args_list[0]
        assert signal_call[0][0] == f"{STREAM_SIGNAL_PREFIX}s1"
        assert signal_call[0][1] == "cancelled"

        # Second call: progress with is_cancelled=True
        progress_call = self.mock_set.call_args_list[1]
        assert progress_call[0][1]["is_cancelled"] is True

    async def test_publishes_cancelled_signal(self) -> None:
        await StreamManager.cancel_stream("s1")

        self.mock_redis_client.publish.assert_awaited_once_with(
            f"{STREAM_CHANNEL_PREFIX}s1",
            STREAM_CANCELLED_SIGNAL,
        )

    async def test_cancel_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        result = await StreamManager.cancel_stream("s1")
        assert result is True

        # Signal should still be set, but progress update skipped
        # First set is for signal key, no second set for progress
        signal_call = self.mock_set.call_args_list[0]
        assert signal_call[0][0] == f"{STREAM_SIGNAL_PREFIX}s1"
        # Only 1 set call (signal), not 2
        assert self.mock_set.await_count == 1


# ---------------------------------------------------------------------------
# is_cancelled
# ---------------------------------------------------------------------------


class TestIsCancelled:
    async def test_returns_true_when_cancelled(self) -> None:
        mock_get = AsyncMock(return_value="cancelled")
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.is_cancelled("s1")
        assert result is True
        mock_get.assert_awaited_once_with(f"{STREAM_SIGNAL_PREFIX}s1")

    async def test_returns_false_when_not_cancelled(self) -> None:
        mock_get = AsyncMock(return_value=None)
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.is_cancelled("s1")
        assert result is False

    async def test_returns_false_for_different_signal(self) -> None:
        mock_get = AsyncMock(return_value="something_else")
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.is_cancelled("s1")
        assert result is False


# ---------------------------------------------------------------------------
# update_progress
# ---------------------------------------------------------------------------


class TestUpdateProgress:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.progress = _progress_dict()
        self.mock_get = AsyncMock(return_value=self.progress)
        self.mock_set = AsyncMock()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=self.mock_get, set=self.mock_set),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_appends_message_chunk(self) -> None:
        self.progress["complete_message"] = "Hello "
        await StreamManager.update_progress("s1", message_chunk="World")

        saved = self.mock_set.call_args[0][1]
        assert saved["complete_message"] == "Hello World"

    async def test_merges_tool_data(self) -> None:
        self.progress["tool_data"] = {"existing": "data"}
        await StreamManager.update_progress("s1", tool_data={"new_key": "new_value"})

        saved = self.mock_set.call_args[0][1]
        assert saved["tool_data"]["existing"] == "data"
        assert saved["tool_data"]["new_key"] == "new_value"

    async def test_merges_tool_data_arrays(self) -> None:
        """When both existing and new have 'tool_data' key, arrays are concatenated."""
        self.progress["tool_data"] = {"tool_data": [{"id": 1}]}
        await StreamManager.update_progress("s1", tool_data={"tool_data": [{"id": 2}]})

        saved = self.mock_set.call_args[0][1]
        assert saved["tool_data"]["tool_data"] == [{"id": 1}, {"id": 2}]

    async def test_noop_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        await StreamManager.update_progress("s1", message_chunk="hello")
        self.mock_set.assert_not_awaited()

    async def test_no_update_when_no_chunk_or_tool_data(self) -> None:
        """Even with empty args, set is still called (progress_data exists)."""
        await StreamManager.update_progress("s1")
        # set is still called because progress_data was found
        self.mock_set.assert_awaited_once()

    async def test_message_chunk_appends_to_empty(self) -> None:
        self.progress["complete_message"] = ""
        await StreamManager.update_progress("s1", message_chunk="first")

        saved = self.mock_set.call_args[0][1]
        assert saved["complete_message"] == "first"


# ---------------------------------------------------------------------------
# get_progress
# ---------------------------------------------------------------------------


class TestGetProgress:
    async def test_returns_progress_data(self) -> None:
        expected = _progress_dict()
        mock_get = AsyncMock(return_value=expected)
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.get_progress("s1")

        assert result == expected
        mock_get.assert_awaited_once_with(f"{STREAM_PROGRESS_PREFIX}s1")

    async def test_returns_none_when_not_found(self) -> None:
        mock_get = AsyncMock(return_value=None)
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.get_progress("s1")

        assert result is None


# ---------------------------------------------------------------------------
# set_error
# ---------------------------------------------------------------------------


class TestSetError:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.progress = _progress_dict()
        self.mock_get = AsyncMock(return_value=self.progress)
        self.mock_set = AsyncMock()
        self.mock_redis_client = MagicMock()
        self.mock_redis_client.publish = AsyncMock()

        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(
                get=self.mock_get,
                set=self.mock_set,
                redis=self.mock_redis_client,
            ),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_records_error_and_publishes_signal(self) -> None:
        await StreamManager.set_error("s1", "kaboom")

        saved = self.mock_set.call_args[0][1]
        assert saved["error"] == "kaboom"

        self.mock_redis_client.publish.assert_awaited_once_with(
            f"{STREAM_CHANNEL_PREFIX}s1",
            STREAM_ERROR_SIGNAL,
        )

    async def test_publishes_error_even_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        await StreamManager.set_error("s1", "kaboom")

        self.mock_set.assert_not_awaited()
        # Error signal should still be published
        self.mock_redis_client.publish.assert_awaited_once()
