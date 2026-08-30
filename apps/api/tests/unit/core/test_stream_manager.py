"""Tests for StreamManager — Redis Streams event-log lifecycle.

Covers: start (progress + active-stream reverse index), complete, cleanup,
publish (XADD to the replayable event log), subscribe (replay with SSE id
lines, cursor resume, control signals, keepalives), cancel, is_cancelled,
get_active_stream_id, progress tracking, and error recording.
"""

from collections.abc import Generator
from dataclasses import asdict
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.cache import (
    STREAM_ACTIVE_PREFIX,
    STREAM_EVENTS_MAXLEN,
    STREAM_EVENTS_PREFIX,
    STREAM_LIVENESS_REFRESH_AFTER,
    STREAM_PROGRESS_PREFIX,
    STREAM_SIGNAL_PREFIX,
    STREAM_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.streaming import (
    STREAM_CANCELLED_SIGNAL,
    STREAM_DONE_SIGNAL,
    STREAM_ERROR_SIGNAL,
)
from app.core.stream_manager import StreamManager, StreamProgress
from tests.helpers import captured_wide_event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EVENTS_KEY = f"{STREAM_EVENTS_PREFIX}s1"
ACTIVE_KEY = f"{STREAM_ACTIVE_PREFIX}user-1:conv-1"

XReadBatch = list[tuple[str, list[tuple[str, dict[str, str]]]]]


def _progress_dict(**overrides: Any) -> dict[str, Any]:
    """Return a dict that mirrors what Redis stores for StreamProgress.

    Pass any field as a keyword to override its default, e.g.
    ``_progress_dict(is_cancelled=True)``.
    """
    return {
        "conversation_id": "conv-1",
        "user_id": "user-1",
        "complete_message": "",
        "tool_data": {},
        "started_at": "2026-01-01T00:00:00+00:00",
        "is_cancelled": False,
        "is_complete": False,
        "error": None,
        **overrides,
    }


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

    async def test_stores_active_stream_reverse_index(self) -> None:
        await StreamManager.start_stream("s1", "conv-1", "user-1")

        assert self.mock_set.await_count == 2
        active_call = self.mock_set.call_args_list[1]
        assert active_call[0][0] == ACTIVE_KEY
        assert active_call[0][1] == "s1"
        assert active_call[1]["ttl"] == STREAM_TTL


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

        # Active-stream reverse index cleared
        self.mock_delete.assert_awaited_once_with(ACTIVE_KEY)

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
        self.mock_get = AsyncMock(return_value=_progress_dict())
        self.mock_delete = AsyncMock()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=self.mock_get, delete=self.mock_delete),
        )
        patcher.start()
        yield
        patcher.stop()

    async def test_deletes_progress_signal_and_active_keys(self) -> None:
        await StreamManager.cleanup("s1")

        calls = [c[0][0] for c in self.mock_delete.call_args_list]
        assert ACTIVE_KEY in calls
        assert f"{STREAM_PROGRESS_PREFIX}s1" in calls
        assert f"{STREAM_SIGNAL_PREFIX}s1" in calls

    async def test_keeps_replayable_event_log(self) -> None:
        """The event log must survive cleanup so late re-attach can still replay."""
        await StreamManager.cleanup("s1")

        calls = [c[0][0] for c in self.mock_delete.call_args_list]
        assert EVENTS_KEY not in calls

    async def test_skips_active_index_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        await StreamManager.cleanup("s1")

        calls = [c[0][0] for c in self.mock_delete.call_args_list]
        assert ACTIVE_KEY not in calls
        assert f"{STREAM_PROGRESS_PREFIX}s1" in calls
        assert f"{STREAM_SIGNAL_PREFIX}s1" in calls


# ---------------------------------------------------------------------------
# get_active_stream_id
# ---------------------------------------------------------------------------


class TestGetActiveStreamId:
    async def test_returns_stream_id(self) -> None:
        mock_get = AsyncMock(return_value="s1")
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.get_active_stream_id("user-1", "conv-1")

        assert result == "s1"
        mock_get.assert_awaited_once_with(ACTIVE_KEY)

    async def test_returns_none_when_missing(self) -> None:
        mock_get = AsyncMock(return_value=None)
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.get_active_stream_id("user-1", "conv-1")

        assert result is None

    async def test_returns_none_for_non_string_value(self) -> None:
        mock_get = AsyncMock(return_value={"unexpected": "shape"})
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(get=mock_get),
        ):
            result = await StreamManager.get_active_stream_id("user-1", "conv-1")

        assert result is None


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


# ---------------------------------------------------------------------------
# subscribe_stream
# ---------------------------------------------------------------------------


class TestSubscribeStream:
    def _patch_redis(self, client: MagicMock, get: AsyncMock | None = None) -> Any:
        return patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=client, get=get or AsyncMock(return_value=None)),
        )

    async def _collect(self, stream_id: str = "s1", **kwargs: Any) -> list[str]:
        chunks: list[str] = []
        async for chunk in StreamManager.subscribe_stream(stream_id, **kwargs):
            chunks.append(chunk)
        return chunks

    async def test_yields_id_tagged_frames_until_done(self) -> None:
        client = _stream_client(
            [
                _entries_batch(
                    ("1-0", "data: chunk1\n\n"),
                    ("2-0", "data: chunk2\n\n"),
                    ("3-0", STREAM_DONE_SIGNAL),
                ),
            ]
        )

        with self._patch_redis(client):
            chunks = await self._collect()

        assert chunks == [
            "id: 1-0\ndata: chunk1\n\n",
            "id: 2-0\ndata: chunk2\n\n",
        ]

    async def test_entry_missing_a_data_field_yields_empty_data_not_a_placeholder(self) -> None:
        # A Stream entry with no "data" field defaults to the empty string, so the
        # frame carries an empty body — never "None" or a placeholder token.
        client = _stream_client(
            [[(EVENTS_KEY, [("1-0", {}), ("2-0", {"data": STREAM_DONE_SIGNAL})])]]
        )

        with self._patch_redis(client):
            chunks = await self._collect()

        assert chunks == ["id: 1-0\n"]

    async def test_reads_from_beginning_by_default(self) -> None:
        client = _stream_client([_entries_batch(("1-0", STREAM_DONE_SIGNAL))])

        with self._patch_redis(client):
            await self._collect()

        client.xread.assert_awaited_once_with({EVENTS_KEY: "0-0"}, block=15000, count=256)

    async def test_resumes_from_last_event_id(self) -> None:
        client = _stream_client([_entries_batch(("6-0", STREAM_DONE_SIGNAL))])

        with self._patch_redis(client):
            await self._collect(last_event_id="5-0")

        first_call = client.xread.await_args_list[0]
        assert first_call[0][0] == {EVENTS_KEY: "5-0"}

    async def test_advances_cursor_between_reads(self) -> None:
        client = _stream_client(
            [
                _entries_batch(("1-0", "data: a\n\n"), ("2-0", "data: b\n\n")),
                _entries_batch(("3-0", STREAM_DONE_SIGNAL)),
            ]
        )

        with self._patch_redis(client):
            chunks = await self._collect()

        assert chunks == ["id: 1-0\ndata: a\n\n", "id: 2-0\ndata: b\n\n"]
        second_call = client.xread.await_args_list[1]
        assert second_call[0][0] == {EVENTS_KEY: "2-0"}

    async def test_cancelled_signal_yields_done_marker(self) -> None:
        client = _stream_client(
            [
                _entries_batch(
                    ("1-0", "data: chunk1\n\n"),
                    ("2-0", STREAM_CANCELLED_SIGNAL),
                ),
            ]
        )

        with self._patch_redis(client):
            chunks = await self._collect()

        assert chunks == ["id: 1-0\ndata: chunk1\n\n", "data: [DONE]\n\n"]

    async def test_error_signal_yields_error_json(self) -> None:
        client = _stream_client([_entries_batch(("1-0", STREAM_ERROR_SIGNAL))])
        mock_get = AsyncMock(return_value=_progress_dict(error="Something failed"))

        with self._patch_redis(client, get=mock_get):
            chunks = await self._collect()

        assert chunks == ['data: {"error": "Something failed"}\n\n']

    async def test_error_signal_with_no_progress_uses_default(self) -> None:
        client = _stream_client([_entries_batch(("1-0", STREAM_ERROR_SIGNAL))])
        mock_get = AsyncMock(return_value=None)

        with self._patch_redis(client, get=mock_get):
            chunks = await self._collect()

        payload = json.loads(chunks[0].removeprefix("data: ").strip())
        assert payload["error"] == "An unexpected error occurred"

    async def test_error_signal_defaults_when_progress_lacks_error_key(self) -> None:
        # Progress exists but carries no `error` key: the `.get` default (a distinct
        # code path from the no-progress branch above) must supply the message.
        client = _stream_client([_entries_batch(("1-0", STREAM_ERROR_SIGNAL))])
        mock_get = AsyncMock(return_value={"conversation_id": "c"})

        with self._patch_redis(client, get=mock_get):
            chunks = await self._collect()

        assert chunks == ['data: {"error": "An unexpected error occurred"}\n\n']

    async def test_error_signal_reads_progress_for_this_stream_and_logs_it(self) -> None:
        # The error frame is built from THIS stream's progress, and the failure is
        # recorded on the wide event — a mutant that reads another stream (or None)
        # would serve the wrong error or crash.
        client = _stream_client([_entries_batch(("1-0", STREAM_ERROR_SIGNAL))])
        with (
            self._patch_redis(client),
            patch.object(
                StreamManager, "get_progress", new=AsyncMock(return_value={"error": "x"})
            ) as get_progress,
        ):
            async with captured_wide_event() as event:
                _ = [chunk async for chunk in StreamManager.subscribe_stream("sid-9")]

        get_progress.assert_awaited_once_with("sid-9")
        (error,) = [e for e in event["errors"] if "Stream encountered" in e["msg"]]
        assert error["msg"] == f"{LogTag.STARTUP} Stream encountered an error"
        assert error["stream_id"] == "sid-9"

    async def test_warns_when_the_stream_ends_without_any_chunk(self) -> None:
        # DONE with no data frames before it: the client got nothing, which is
        # the one condition worth an operator warning.
        client = _stream_client([_entries_batch(("1-0", STREAM_DONE_SIGNAL))])
        with self._patch_redis(client):
            async with captured_wide_event() as event:
                _ = await self._collect(stream_id="sid-empty")
        warnings = [w for w in event["warnings"] if "without receiving any chunks" in w["msg"]]
        assert len(warnings) == 1
        assert warnings[0]["stream_id"] == "sid-empty"

    async def test_no_warning_when_a_chunk_was_delivered(self) -> None:
        client = _stream_client(
            [_entries_batch(("1-0", "data: hi\n\n"), ("2-0", STREAM_DONE_SIGNAL))]
        )
        with self._patch_redis(client):
            async with captured_wide_event() as event:
                _ = await self._collect()
        assert [
            w for w in event.get("warnings", []) if "without receiving any chunks" in w["msg"]
        ] == []

    async def test_subscription_error_is_logged_and_yields_an_error_frame(self) -> None:
        client = _stream_client()
        client.xread = AsyncMock(side_effect=RuntimeError("redis blew up"))
        with self._patch_redis(client):
            async with captured_wide_event() as event:
                chunks = await self._collect()
        assert chunks == ['data: {"error": "Stream subscription failed"}\n\n']
        (error,) = [e for e in event["errors"] if "Error in stream subscription" in e["msg"]]
        assert error["msg"] == f"{LogTag.STARTUP} Error in stream subscription"
        assert error["error_type"] == "RuntimeError"

    async def test_keepalive_on_idle_read(self) -> None:
        """An empty XREAD (idle interval) yields a keepalive frame with no id line."""
        client = _stream_client(
            [
                [],  # blocked read timed out -> keepalive
                _entries_batch(("1-0", STREAM_DONE_SIGNAL)),
            ]
        )

        with self._patch_redis(client):
            chunks = await self._collect(keepalive_interval=0.01)

        assert chunks == ['data: {"keepalive":true}\n\n']

    async def test_returns_immediately_when_redis_unavailable(self) -> None:
        with patch(
            "app.core.stream_manager.redis_cache",
            new=MagicMock(redis=None),
        ):
            chunks = await self._collect()

        assert chunks == []

    async def test_exception_during_read_yields_error(self) -> None:
        client = MagicMock()
        client.xread = AsyncMock(side_effect=RuntimeError("connection lost"))

        with self._patch_redis(client):
            chunks = await self._collect()

        assert len(chunks) == 1
        payload = json.loads(chunks[0].removeprefix("data: ").strip())
        assert payload["error"] == "Stream subscription failed"

    async def test_warning_logged_when_no_chunks_received(self) -> None:
        """When stream ends with zero data chunks, a warning should be logged."""
        client = _stream_client([_entries_batch(("1-0", STREAM_DONE_SIGNAL))])

        with (
            self._patch_redis(client),
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

    async def test_clears_active_index(self) -> None:
        await StreamManager.cancel_stream("s1")

        self.mock_delete.assert_awaited_once_with(ACTIVE_KEY)

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


class TestUpdateProgress:
    @pytest.fixture(autouse=True)
    def _patch_redis(self) -> Generator[None, None, None]:
        self.progress = _progress_dict()
        self.mock_get = AsyncMock(return_value=self.progress)
        self.mock_set = AsyncMock()
        patcher = patch(
            "app.core.stream_manager.redis_cache",
            # ``redis`` must be async: update_progress also refreshes the resume
            # index through it (see _refresh_active_index). TTL behaviour itself
            # is covered against a real client in tests/unit/core/test_stream_resume.py.
            new=MagicMock(get=self.mock_get, set=self.mock_set, redis=AsyncMock()),
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

    async def test_records_error_and_appends_error_signal(self) -> None:
        await StreamManager.set_error("s1", "kaboom")

        saved = self.mock_set.call_args[0][1]
        assert saved["error"] == "kaboom"

        self.mock_redis_client.xadd.assert_awaited_once_with(
            EVENTS_KEY,
            {"data": STREAM_ERROR_SIGNAL},
            maxlen=STREAM_EVENTS_MAXLEN,
            approximate=True,
        )

    async def test_appends_error_even_when_progress_missing(self) -> None:
        self.mock_get.return_value = None
        await StreamManager.set_error("s1", "kaboom")

        self.mock_set.assert_not_awaited()
        # Error signal should still be appended
        self.mock_redis_client.xadd.assert_awaited_once()


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
