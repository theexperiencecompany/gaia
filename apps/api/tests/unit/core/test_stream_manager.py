"""Tests for StreamManager — Redis Streams event-log lifecycle.

Covers: start (progress), complete, cleanup,
publish (XADD to the replayable event log), subscribe (replay with SSE id
lines, cursor resume, control signals, keepalives), cancel, is_cancelled,
progress tracking, and error recording.
"""

from collections.abc import Generator
from dataclasses import asdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus_client import REGISTRY
import pytest

from app.constants.cache import (
    STREAM_EVENTS_MAXLEN,
    STREAM_EVENTS_PREFIX,
    STREAM_LIVENESS_REFRESH_AFTER,
    STREAM_PROGRESS_PREFIX,
    STREAM_SIGNAL_PREFIX,
    STREAM_TTL,
)
from app.constants.streaming import STREAM_CANCELLED_SIGNAL, STREAM_DONE_SIGNAL
from app.core.stream_manager import StreamManager, StreamProgress

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EVENTS_KEY = f"{STREAM_EVENTS_PREFIX}s1"
PROGRESS_KEY = f"{STREAM_PROGRESS_PREFIX}s1"

XReadBatch = list[tuple[str, list[tuple[str, dict[str, str]]]]]


def _progress_dict(**overrides: Any) -> dict[str, Any]:
    """Return a dict that mirrors what Redis stores for StreamProgress.

    Pass any field as a keyword to override its default, e.g.
    _progress_dict(is_cancelled=True).
    """
    return {
        "conversation_id": "conv-1",
        "user_id": "user-1",
        "complete_message": "",
        "pending_message": "",
        "tool_data": {},
        "started_at": "2026-01-01T00:00:00+00:00",
        "is_cancelled": False,
        "is_complete": False,
        "error": None,
        **overrides,
    }


def _progress_get(progress: dict[str, Any]) -> AsyncMock:
    """Serve s1's progress record from a fake redis_cache.get, under its real key only."""
    return AsyncMock(side_effect=lambda key: progress if key == PROGRESS_KEY else None)


def _entries_batch(*entries: tuple[str, str]) -> XReadBatch:
    """Build an XREAD result batch: [(events_key, [(entry_id, {"data": ...})])]."""
    return [(EVENTS_KEY, [(entry_id, {"data": data}) for entry_id, data in entries])]


def _stream_client(xread_batches: list[XReadBatch] | None = None) -> MagicMock:
    """Mock redis.asyncio client exposing the Streams commands StreamManager uses."""
    client = MagicMock()
    client.xadd = AsyncMock()
    client.expire = AsyncMock()
    # A full-TTL progress key: publish_chunk's liveness refresh reads this and
    # returns early, so these tests see only the event-log write they assert on.
    client.ttl = AsyncMock(return_value=STREAM_TTL)
    if xread_batches is not None:
        client.xread = AsyncMock(side_effect=xread_batches)
    return client


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

        progress_call = self.mock_set.call_args_list[0]
        key = progress_call[0][0]
        data = progress_call[0][1]

        assert key == f"{STREAM_PROGRESS_PREFIX}s1"
        assert data["conversation_id"] == "conv-1"
        assert data["user_id"] == "user-1"
        assert data["is_complete"] is False
        assert data["is_cancelled"] is False
        assert progress_call[1]["ttl"] == STREAM_TTL


# ---------------------------------------------------------------------------
# complete_stream
# ---------------------------------------------------------------------------


class TestCompleteStream:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.mock_get = AsyncMock(return_value=_progress_dict())
        self.mock_set = AsyncMock()
        self.mock_delete = AsyncMock()
        self.mock_redis_client = _stream_client()

        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(
                get=self.mock_get,
                set=self.mock_set,
                delete=self.mock_delete,
                redis=self.mock_redis_client,
            ),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_marks_progress_complete_and_appends_done(self) -> None:
        await StreamManager.complete_stream("s1")

        # Progress updated with is_complete=True
        set_call = self.mock_set.call_args
        data = set_call[0][1]
        assert data["is_complete"] is True

        # DONE signal appended to the event log with retention + TTL
        self.mock_redis_client.xadd.assert_awaited_once_with(
            EVENTS_KEY,
            {"data": STREAM_DONE_SIGNAL},
            maxlen=STREAM_EVENTS_MAXLEN,
            approximate=True,
        )
        self.mock_redis_client.expire.assert_awaited_once_with(EVENTS_KEY, STREAM_TTL)

    async def test_appends_done_even_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        await StreamManager.complete_stream("s1")

        # set/delete should NOT be called when progress_data is None
        self.mock_set.assert_not_awaited()
        self.mock_delete.assert_not_awaited()
        # but the DONE signal should still be appended
        self.mock_redis_client.xadd.assert_awaited_once()


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.progress: dict[str, Any] | None = _progress_dict()
        self.mock_get = AsyncMock(
            side_effect=lambda key: self.progress if key == PROGRESS_KEY else None
        )
        self.mock_delete = AsyncMock()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=self.mock_get, delete=self.mock_delete),
        )
        patcher.start()
        yield
        patcher.stop()


# ---------------------------------------------------------------------------
# publish_chunk
# ---------------------------------------------------------------------------


class TestPublishChunk:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.mock_redis_client = _stream_client()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=self.mock_redis_client),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_appends_chunk_to_event_log(self) -> None:
        await StreamManager.publish_chunk("s1", "data: hello\n\n")

        self.mock_redis_client.xadd.assert_awaited_once_with(
            EVENTS_KEY,
            {"data": "data: hello\n\n"},
            maxlen=STREAM_EVENTS_MAXLEN,
            approximate=True,
        )

    async def test_refreshes_event_log_ttl(self) -> None:
        await StreamManager.publish_chunk("s1", "data: hello\n\n")

        self.mock_redis_client.expire.assert_awaited_once_with(EVENTS_KEY, STREAM_TTL)

    async def test_noop_when_redis_unavailable(self) -> None:
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=None),
        ):
            # Should not raise
            await StreamManager.publish_chunk("s1", "data: hello\n\n")

    async def test_publish_observes_transport_span(self) -> None:
        before = REGISTRY.get_sample_value("transport_redis_publish_seconds_count", {}) or 0.0
        await StreamManager.publish_chunk("s1", "data: hello\n\n")
        assert REGISTRY.get_sample_value("transport_redis_publish_seconds_count", {}) == before + 1

    async def test_no_observation_without_redis(self) -> None:
        before = REGISTRY.get_sample_value("transport_redis_publish_seconds_count", {}) or 0.0
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=None),
        ):
            await StreamManager.publish_chunk("s1", "data: hello\n\n")
        assert REGISTRY.get_sample_value("transport_redis_publish_seconds_count", {}) == before

    async def test_publish_records_exact_elapsed_seconds(self) -> None:
        # Two pinned clock reads land exactly 0.5; a sign error (end + start) would
        # record 200.5, so this pins the direction of the subtraction, not just that
        # an observation happened.
        before = REGISTRY.get_sample_value("transport_redis_publish_seconds_sum", {}) or 0.0
        with patch(
            "app.core.stream_manager.time.perf_counter",
            side_effect=[100.0, 100.5],
        ):
            await StreamManager.publish_chunk("s1", "data: hello\n\n")
        after = REGISTRY.get_sample_value("transport_redis_publish_seconds_sum", {})
        assert after == before + 0.5


# ---------------------------------------------------------------------------
# subscribe_stream
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# cancel_stream
# ---------------------------------------------------------------------------


class TestCancelStream:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.mock_set = AsyncMock()
        self.mock_get = AsyncMock(return_value=_progress_dict())
        self.mock_delete = AsyncMock()
        self.mock_redis_client = _stream_client()

        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(
                set=self.mock_set,
                get=self.mock_get,
                delete=self.mock_delete,
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

    async def test_appends_cancelled_signal(self) -> None:
        await StreamManager.cancel_stream("s1")

        self.mock_redis_client.xadd.assert_awaited_once_with(
            EVENTS_KEY,
            {"data": STREAM_CANCELLED_SIGNAL},
            maxlen=STREAM_EVENTS_MAXLEN,
            approximate=True,
        )

    async def test_cancel_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        result = await StreamManager.cancel_stream("s1")
        assert result is True

        # Signal should still be set, but progress update and index clear skipped
        signal_call = self.mock_set.call_args_list[0]
        assert signal_call[0][0] == f"{STREAM_SIGNAL_PREFIX}s1"
        assert self.mock_set.await_count == 1
        self.mock_delete.assert_not_awaited()
        # Cancelled signal still appended so subscribers terminate
        self.mock_redis_client.xadd.assert_awaited_once()


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
        self.mock_get = _progress_get(self.progress)
        self.mock_set = AsyncMock()
        self.mock_redis_client = _stream_client()

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


# ---------------------------------------------------------------------------
# _touch_liveness — the TTL-window throttle
# ---------------------------------------------------------------------------


class TestTouchLiveness:
    @staticmethod
    def _patched(ttl_value: int):
        client = MagicMock()
        client.ttl = AsyncMock(return_value=ttl_value)
        client.expire = AsyncMock()
        rc = MagicMock(redis=client)
        rc.get = AsyncMock(return_value=None)
        return patch("app.core.stream_manager.redis_cache", new=rc), client

    @pytest.mark.parametrize("ttl_value", [0, STREAM_LIVENESS_REFRESH_AFTER])
    async def test_refreshes_inside_the_window(self, ttl_value: int) -> None:
        # 0 and exactly REFRESH_AFTER are the inclusive boundaries that MUST refresh.
        patcher, client = self._patched(ttl_value)
        with patcher:
            await StreamManager._touch_liveness("s1")
        client.expire.assert_awaited_once_with(f"{STREAM_PROGRESS_PREFIX}s1", STREAM_TTL)

    @pytest.mark.parametrize("ttl_value", [-1, STREAM_LIVENESS_REFRESH_AFTER + 1])
    async def test_skips_outside_the_window(self, ttl_value: int) -> None:
        # A missing/no-TTL key (<0) or one still far from expiry must not refresh.
        patcher, client = self._patched(ttl_value)
        with patcher:
            await StreamManager._touch_liveness("s1")
        client.expire.assert_not_awaited()
