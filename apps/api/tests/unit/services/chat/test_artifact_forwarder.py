"""Unit tests for the per-turn artifact forwarder (app/services/chat/artifact_forwarder.py).

The forwarder is a pipeline over five steps: stream live (SSE), save (registry +
message ref), deliver to bot, warm cache. These tests lock:

- the exact routing rules of ``_handle_event`` (remove wins over a matching
  mtime; unchanged re-emits are skipped; anything else goes through the upsert
  pipeline) and the dedup maps that back them;
- the exact payloads/args handed to every seam (SSE chunk bytes, registry
  repo calls, outbound file envelope kwargs, session path resolution);
- the failure modes: one bad pub/sub event is logged and skipped, persist
  retries with backoff and gives up with a warning, ``run`` logs and exits on
  subscribe/registry errors, teardown and cancellation always close pubsub;
- the module helpers: ``_parse_artifact_message`` filtering, ``_bot_source``
  mapping, ``_close_pubsub`` error swallowing, ``_warm_artifact_blocks`` chunk
  draining.

Seams mocked: redis pubsub, stream manager, conversation repository, the
registry CRUD, the outbound publisher, session-path resolution, and the
pure entry builders. The forwarder itself is never mocked.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.artifacts import (
    ARTIFACT_LOG_PREFIX,
    ARTIFACT_PERSIST_MAX_ATTEMPTS,
    ARTIFACT_PERSIST_RETRY_BASE_DELAY,
    ARTIFACT_WARM_CHUNK_BYTES,
)
from app.models.chat_models import ConversationSource
from app.services.chat import artifact_forwarder as af

USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-1"
STREAM_ID = "stream-1"
BOT_MESSAGE_ID = "msg-1"

FULL_ENTRY: dict[str, Any] = {
    "tool_name": "artifact_data",
    "data": {"marker": "full"},
    "timestamp": "t0",
    "tool_category": "artifact",
}
REF_ENTRY: dict[str, Any] = {
    "tool_name": "artifact_data",
    "data": {"marker": "ref"},
    "timestamp": "t1",
    "tool_category": "artifact",
}


def _payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "event": "upsert",
        "session_id": CONVERSATION_ID,
        "path": "artifacts/notes.md",
        "size_bytes": 12,
        "mtime": 1234.5,
        "content_type": "text/markdown",
    }
    data.update(overrides)
    return data


def _message(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "message", "data": json.dumps(payload)}


def _forwarder(
    source: str | None = None,
    bot_message_id: str | None = BOT_MESSAGE_ID,
    subscribed: asyncio.Event | None = None,
) -> af.ArtifactForwarder:
    return af.ArtifactForwarder(USER_ID, CONVERSATION_ID, STREAM_ID, bot_message_id, source, subscribed)


async def _listen(messages: list[dict[str, Any]]) -> AsyncGenerator[dict[str, Any], None]:
    for message in messages:
        yield message


def _make_pubsub(messages: list[dict[str, Any]] | None = None) -> SimpleNamespace:
    """A redis pubsub stand-in: ``listen`` is a sync callable (the code does
    ``async for message in pubsub.listen()``, so it must return the generator
    directly, not a coroutine); the teardown methods are awaited AsyncMocks."""
    pubsub = SimpleNamespace()
    pubsub.listen = lambda: _listen(messages or [])
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    return pubsub


@contextmanager
def _patches():
    """Patch every module-level seam; ``spawned`` collects spawned coroutines."""
    captured: list[Any] = []
    with (
        patch.object(af, "log") as log_mock,
        patch.object(af, "stream_manager", new=AsyncMock()) as sm,
        patch.object(af, "conversation_repository", new=AsyncMock()) as conv_repo,
        patch.object(af, "get_conversation_artifacts", new=AsyncMock(return_value=[])) as get_registry,
        patch.object(af, "upsert_conversation_artifact", new_callable=AsyncMock) as upsert,
        patch.object(af, "remove_conversation_artifact", new_callable=AsyncMock) as remove_registry,
        patch.object(af, "build_artifact_full_entry", return_value=FULL_ENTRY) as build_full,
        patch.object(af, "build_artifact_ref_entry", return_value=REF_ENTRY) as build_ref,
        patch.object(af, "publish_outbound_file", new_callable=AsyncMock) as publish_file,
        patch.object(af, "spawn_background_task", side_effect=captured.append) as spawn,
        patch.object(af, "resolve_session_path", new_callable=AsyncMock) as resolve_path,
        patch.object(af, "_warm_artifact_blocks") as warm_blocks,
        patch.object(af, "_warm_semaphore", new=AsyncMock()) as warm_sem,
    ):
        yield SimpleNamespace(
            log=log_mock,
            sm=sm,
            conv_repo=conv_repo,
            get_registry=get_registry,
            upsert=upsert,
            remove_registry=remove_registry,
            build_full=build_full,
            build_ref=build_ref,
            publish_file=publish_file,
            spawn=spawn,
            resolve_path=resolve_path,
            warm_blocks=warm_blocks,
            warm_sem=warm_sem,
            spawned=captured,
        )


class TestInit:
    def test_sets_all_state(self) -> None:
        f = af.ArtifactForwarder(USER_ID, CONVERSATION_ID, STREAM_ID, BOT_MESSAGE_ID, "telegram")

        assert (f.user_id, f.conversation_id, f.stream_id, f.bot_message_id) == (
            USER_ID,
            CONVERSATION_ID,
            STREAM_ID,
            BOT_MESSAGE_ID,
        )
        assert f.bot_platform is ConversationSource.TELEGRAM
        assert f.registry_mtimes == {}
        assert f.published_files == set()
        assert (f.stats.upserts, f.stats.removes, f.stats.unchanged, f.stats.delivered) == (0, 0, 0, 0)


class TestBotSource:
    @pytest.mark.parametrize(
        "source", [None, "", "web", "mobile", "desktop", "workflow_system", "background", "nonsense-source"]
    )
    def test_none_for_non_bot_sources(self, source: str | None) -> None:
        assert af._bot_source(source) is None

    @pytest.mark.parametrize("source", ["whatsapp", "telegram", "discord", "slack"])
    def test_maps_bot_sources_to_enum(self, source: str) -> None:
        assert af._bot_source(source) == ConversationSource(source)


class TestParseArtifactMessage:
    def test_rejects_non_message_frames(self) -> None:
        assert af._parse_artifact_message({"type": "subscribe", "data": json.dumps(_payload())}, CONVERSATION_ID) is None

    def test_rejects_invalid_json(self) -> None:
        assert af._parse_artifact_message({"type": "message", "data": "{not json"}, CONVERSATION_ID) is None

    def test_rejects_non_string_data(self) -> None:
        assert af._parse_artifact_message({"type": "message", "data": 123}, CONVERSATION_ID) is None

    def test_rejects_other_conversations(self) -> None:
        assert af._parse_artifact_message(_message(_payload(session_id="other-conv")), CONVERSATION_ID) is None

    def test_returns_payload_for_this_conversation(self) -> None:
        payload = _payload()

        assert af._parse_artifact_message(_message(payload), CONVERSATION_ID) == payload


class TestClosePubsub:
    async def test_unsubscribes_then_closes(self) -> None:
        pubsub = AsyncMock()

        await af._close_pubsub(pubsub, "artifacts:u1")

        pubsub.unsubscribe.assert_awaited_once_with("artifacts:u1")
        pubsub.aclose.assert_awaited_once()

    async def test_swallows_teardown_errors(self) -> None:
        pubsub = AsyncMock()
        pubsub.unsubscribe.side_effect = RuntimeError("gone")
        pubsub.aclose.side_effect = RuntimeError("gone")

        await af._close_pubsub(pubsub, "c")  # must not raise


class TestWarmArtifactBlocks:
    def test_drains_file_in_chunk_sized_reads(self) -> None:
        """The drain must read chunk-sized blocks, stop at EOF, and discard each
        chunk (deque maxlen=0).

        The deque is patched so the guards observe the two failure modes this
        function can have: a sentinel that never matches EOF keeps reading
        forever (a hang), and a nonzero maxlen retains the file in memory
        instead of discarding it. Patching is essential — an unguarded run of a
        hang mutant would stall the whole mutation lane for the timeout.
        """
        fake = _FakePath([b"x" * 10, b"y" * 20])

        def _bounded_deque(iterable: Any, maxlen: int | None = None) -> None:
            for reads, _ in enumerate(iterable, start=1):
                if reads > 3:  # 2 chunks + EOF sentinel
                    raise AssertionError("reader did not stop at EOF")
            assert maxlen == 0, f"deque must discard chunks (maxlen=0), got {maxlen!r}"

        with patch.object(af, "deque", side_effect=_bounded_deque) as deque_mock:
            af._warm_artifact_blocks(fake)  # type: ignore[arg-type]  # duck-typed Path seam

        deque_mock.assert_called_once()
        assert fake.modes == ["rb"]
        assert fake.handle.reads == [ARTIFACT_WARM_CHUNK_BYTES, ARTIFACT_WARM_CHUNK_BYTES, ARTIFACT_WARM_CHUNK_BYTES]


class TestTurnStats:
    def test_as_wide_event_exact_shape(self) -> None:
        s = af._TurnStats(upserts=1, removes=2, unchanged=3, delivered=4)

        assert s.as_wide_event("conv-9") == {
            "conversation_id": "conv-9",
            "upserts": 1,
            "removes": 2,
            "unchanged": 3,
            "delivered_to_bot": 4,
        }


class TestLogSummary:
    def test_emits_exact_wide_event_and_summary(self) -> None:
        f = _forwarder()
        f.stats = af._TurnStats(upserts=2, removes=3, unchanged=4, delivered=5)

        with patch.object(af, "log") as log_mock:
            f._log_summary()

        log_mock.set.assert_called_once_with(
            artifacts={
                "conversation_id": CONVERSATION_ID,
                "upserts": 2,
                "removes": 3,
                "unchanged": 4,
                "delivered_to_bot": 5,
            }
        )
        log_mock.info.assert_called_once_with(
            "closed",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            upserts=2,
            removes=3,
            unchanged=4,
            delivered=5,
        )


class TestSignalSubscribed:
    def test_noop_when_no_event(self) -> None:
        f = _forwarder(subscribed=None)

        f._signal_subscribed()  # must not raise

    def test_sets_event(self) -> None:
        subscribed = asyncio.Event()
        f = _forwarder(subscribed=subscribed)

        f._signal_subscribed()

        assert subscribed.is_set()


class TestIsUnchanged:
    def test_true_when_mtimes_match(self) -> None:
        f = _forwarder()
        f.registry_mtimes = {"a.md": 5.0}

        assert f._is_unchanged("a.md", {"mtime": 5.0}) is True

    def test_false_on_different_mtime(self) -> None:
        f = _forwarder()
        f.registry_mtimes = {"a.md": 5.0}

        assert f._is_unchanged("a.md", {"mtime": 6.0}) is False

    def test_false_for_unknown_path_with_mtime(self) -> None:
        f = _forwarder()

        assert f._is_unchanged("new.md", {"mtime": 5.0}) is False

    def test_true_for_unknown_path_without_mtime(self) -> None:
        f = _forwarder()

        assert f._is_unchanged("new.md", {}) is True

    def test_false_without_path(self) -> None:
        f = _forwarder()
        f.registry_mtimes = {"a.md": 5.0}

        assert f._is_unchanged(None, {"mtime": 5.0}) is False


class TestLoadRegistry:
    async def test_seeds_path_to_mtime_map(self) -> None:
        f = _forwarder()
        with _patches() as m:
            m.get_registry.return_value = [
                {"path": "a.txt", "size_bytes": 1, "mtime": 123.0, "content_type": None, "updated_at": "x"},
                {"path": "b.txt", "size_bytes": 2, "mtime": None, "content_type": None, "updated_at": "x"},
            ]

            await f._load_registry()

        m.get_registry.assert_awaited_once_with(USER_ID, CONVERSATION_ID)
        assert f.registry_mtimes == {"a.txt": 123.0, "b.txt": None}


class TestStreamEntry:
    async def test_publishes_sse_data_frame_with_full_entry(self) -> None:
        f = _forwarder()
        entry = af.build_artifact_full_entry(_payload())

        with patch.object(af, "stream_manager", new=AsyncMock()) as sm:
            await f._stream_entry(entry)

        chunk = sm.publish_chunk.await_args.args[1]
        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        assert json.loads(chunk[6:-2]) == {"tool_data": entry}
        sm.publish_chunk.assert_awaited_once_with(STREAM_ID, chunk)


class TestHandleEvent:
    async def test_remove_wins_over_matching_mtime(self) -> None:
        f = _forwarder()
        f.registry_mtimes = {"artifacts/x.txt": 1234.5}
        with _patches() as m:
            await f._handle_event(_payload(event="remove", path="artifacts/x.txt", mtime=1234.5))

        m.remove_registry.assert_awaited_once_with(USER_ID, CONVERSATION_ID, "artifacts/x.txt")
        assert f.stats.unchanged == 0

    async def test_skips_unchanged_reeemit(self) -> None:
        f = _forwarder()
        f.registry_mtimes = {"artifacts/x.txt": 1234.5}
        with _patches() as m:
            await f._handle_event(_payload(path="artifacts/x.txt", mtime=1234.5))
            await f._handle_event(_payload(path="artifacts/x.txt", mtime=1234.5))

        assert f.stats.unchanged == 2  # each re-emit counts once
        m.upsert.assert_not_called()
        m.sm.publish_chunk.assert_not_called()
        m.log.debug.assert_any_call(
            "skip unchanged path", artifact_log_prefix=ARTIFACT_LOG_PREFIX, path="artifacts/x.txt"
        )
        assert m.log.debug.call_count == 2

    async def test_routes_changed_file_to_upsert_pipeline(self) -> None:
        f = _forwarder()
        f.registry_mtimes = {"artifacts/x.txt": 1.0}
        with _patches() as m:
            await f._handle_event(_payload(path="artifacts/x.txt", mtime=2.0))

        m.upsert.assert_awaited_once_with(USER_ID, CONVERSATION_ID, _payload(path="artifacts/x.txt", mtime=2.0))
        m.build_ref.assert_called_once_with(CONVERSATION_ID, "artifacts/x.txt", "upsert")
        assert f.stats.unchanged == 0

    async def test_pathless_payload_is_not_counted_as_unchanged(self) -> None:
        f = _forwarder()
        with _patches() as m:
            await f._handle_event(_payload(path=None, mtime=None))

        assert f.stats.unchanged == 0
        assert f.stats.upserts == 0
        m.log.debug.assert_not_called()


class TestApplyUpsert:
    async def test_without_path_is_noop(self) -> None:
        f = _forwarder()
        with _patches() as m:
            await f._apply_upsert(_payload(path=None), None, "upsert")

        m.build_full.assert_not_called()
        m.sm.publish_chunk.assert_not_called()
        m.upsert.assert_not_called()
        m.build_ref.assert_not_called()
        m.spawn.assert_not_called()
        assert f.stats.upserts == 0
        assert f.registry_mtimes == {}

    async def test_runs_full_pipeline_with_exact_args(self) -> None:
        f = _forwarder(source="slack")
        payload = _payload(body=None)
        with _patches() as m:
            m.resolve_path.return_value = Path("host/artifacts/a.md")
            await f._apply_upsert(payload, "artifacts/a.md", "upsert")

            assert f.registry_mtimes == {"artifacts/a.md": 1234.5}
            assert f.stats.upserts == 1
            m.build_full.assert_called_once_with(payload)
            m.sm.publish_chunk.assert_awaited_once_with(
                STREAM_ID, "data: " + json.dumps({"tool_data": FULL_ENTRY}) + "\n\n"
            )
            m.upsert.assert_awaited_once_with(USER_ID, CONVERSATION_ID, payload)
            m.build_ref.assert_called_once_with(CONVERSATION_ID, "artifacts/a.md", "upsert")
            m.conv_repo.append_message_tool_data.assert_awaited_once_with(
                CONVERSATION_ID, user_id=USER_ID, message_id=BOT_MESSAGE_ID, entries=[REF_ENTRY]
            )
            m.publish_file.assert_called_once_with(
                platform=ConversationSource.SLACK,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                path="artifacts/a.md",
                filename="a.md",
                content_type="text/markdown",
            )
            assert m.spawn.call_count == 2  # one bot delivery + one cache warm
            assert f.stats.delivered == 1
            await m.spawned[0]
            await m.spawned[1]
            m.resolve_path.assert_awaited_once_with(USER_ID, CONVERSATION_ID, "artifacts", "artifacts/a.md")
            m.warm_blocks.assert_called_once_with(Path("host/artifacts/a.md"))

    async def test_upload_event_skips_bot_delivery_and_cache_warm(self) -> None:
        f = _forwarder(source="telegram")
        with _patches() as m:
            await f._apply_upsert(_payload(event="upload"), "uploads/pic.png", "upload")

        m.sm.publish_chunk.assert_awaited_once()
        m.upsert.assert_awaited_once()
        m.build_ref.assert_called_once_with(CONVERSATION_ID, "uploads/pic.png", "upload")
        m.publish_file.assert_not_called()
        m.spawn.assert_not_called()

    async def test_counts_each_upsert(self) -> None:
        f = _forwarder()
        with _patches() as m:
            await f._apply_upsert(_payload(path="a.md"), "a.md", "upsert")
            await f._apply_upsert(_payload(path="b.md"), "b.md", "upsert")

            assert f.stats.upserts == 2
            assert f.registry_mtimes == {"a.md": 1234.5, "b.md": 1234.5}
            assert m.upsert.await_count == 2
            await m.spawned[0]
            await m.spawned[1]


class TestApplyRemove:
    async def test_without_path_is_noop(self) -> None:
        f = _forwarder()
        with _patches() as m:
            await f._apply_remove(None)

        m.build_ref.assert_not_called()
        m.sm.publish_chunk.assert_not_called()
        m.remove_registry.assert_not_called()
        assert f.stats.removes == 0

    async def test_streams_persists_and_clears_registry(self) -> None:
        f = _forwarder()
        f.registry_mtimes = {"artifacts/gone.txt": 1.0, "artifacts/stay.txt": 2.0}
        with _patches() as m:
            await f._apply_remove("artifacts/gone.txt")

        m.build_ref.assert_called_once_with(CONVERSATION_ID, "artifacts/gone.txt", "remove")
        m.sm.publish_chunk.assert_awaited_once_with(
            STREAM_ID, "data: " + json.dumps({"tool_data": REF_ENTRY}) + "\n\n"
        )
        m.remove_registry.assert_awaited_once_with(USER_ID, CONVERSATION_ID, "artifacts/gone.txt")
        m.conv_repo.append_message_tool_data.assert_awaited_once_with(
            CONVERSATION_ID, user_id=USER_ID, message_id=BOT_MESSAGE_ID, entries=[REF_ENTRY]
        )
        m.spawn.assert_not_called()
        assert f.registry_mtimes == {"artifacts/stay.txt": 2.0}
        assert f.stats.removes == 1

    async def test_unknown_path_does_not_raise(self) -> None:
        f = _forwarder()
        with _patches() as m:
            await f._apply_remove("artifacts/ghost.txt")
            await f._apply_remove("artifacts/other.txt")

        assert f.stats.removes == 2  # each remove counts once
        assert m.remove_registry.await_count == 2


class TestPersistEntry:
    async def test_skipped_without_bot_message(self) -> None:
        f = _forwarder(bot_message_id=None)
        with _patches() as m:
            await f._persist_entry(REF_ENTRY)

        m.conv_repo.append_message_tool_data.assert_not_called()

    async def test_matched_first_attempt_returns_immediately(self) -> None:
        f = _forwarder()
        with _patches() as m:
            m.conv_repo.append_message_tool_data.return_value = True
            await f._persist_entry(REF_ENTRY)

        m.conv_repo.append_message_tool_data.assert_awaited_once_with(
            CONVERSATION_ID, user_id=USER_ID, message_id=BOT_MESSAGE_ID, entries=[REF_ENTRY]
        )
        m.log.warning.assert_not_called()

    async def test_returns_when_matched_on_retry(self) -> None:
        f = _forwarder()
        with _patches() as m, patch.object(af.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            m.conv_repo.append_message_tool_data.side_effect = [False, False, True]
            await f._persist_entry(REF_ENTRY)

        assert m.conv_repo.append_message_tool_data.await_count == 3
        sleep_mock.assert_has_awaits(
            [call(ARTIFACT_PERSIST_RETRY_BASE_DELAY * n) for n in (1, 2)]
        )
        m.log.warning.assert_not_called()

    async def test_retries_with_backoff_then_warns(self) -> None:
        f = _forwarder()
        with _patches() as m, patch.object(af.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            m.conv_repo.append_message_tool_data.return_value = False
            await f._persist_entry(REF_ENTRY)

        assert m.conv_repo.append_message_tool_data.await_count == ARTIFACT_PERSIST_MAX_ATTEMPTS
        m.conv_repo.append_message_tool_data.assert_awaited_with(
            CONVERSATION_ID, user_id=USER_ID, message_id=BOT_MESSAGE_ID, entries=[REF_ENTRY]
        )
        sleep_mock.assert_has_awaits(
            [call(ARTIFACT_PERSIST_RETRY_BASE_DELAY * (attempt + 1)) for attempt in range(ARTIFACT_PERSIST_MAX_ATTEMPTS)]
        )
        m.log.warning.assert_called_once_with(
            "persist matched no bot message after retries",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            bot_message_id=BOT_MESSAGE_ID,
        )

    async def test_error_is_swallowed(self) -> None:
        f = _forwarder()
        with _patches() as m:
            m.conv_repo.append_message_tool_data.side_effect = RuntimeError("mongo down")
            await f._persist_entry(REF_ENTRY)

        m.log.warning.assert_called_once_with(
            "failed to persist artifact entry",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            error="mongo down",
            error_type="RuntimeError",
        )


class TestMaybeDeliverToBot:
    def test_skipped_without_bot_platform(self) -> None:
        f = _forwarder(source=None)
        with _patches() as m:
            f._maybe_deliver_to_bot(_payload(), "artifacts/a.md", "upsert")

        m.publish_file.assert_not_called()
        m.spawn.assert_not_called()
        assert f.stats.delivered == 0

    def test_skipped_for_upload_events(self) -> None:
        f = _forwarder(source="telegram")
        with _patches() as m:
            f._maybe_deliver_to_bot(_payload(event="upload"), "uploads/a.png", "upload")

        m.publish_file.assert_not_called()
        assert f.stats.delivered == 0

    async def test_once_per_path(self) -> None:
        f = _forwarder(source="telegram")
        with _patches() as m:
            f._maybe_deliver_to_bot(_payload(), "artifacts/a.md", "upsert")
            f._maybe_deliver_to_bot(_payload(), "artifacts/a.md", "upsert")

            assert m.publish_file.call_count == 1
            m.spawn.assert_called_once()
            assert f.stats.delivered == 1
            assert f.published_files == {"artifacts/a.md"}
            await m.spawned[0]

    async def test_publishes_exact_outbound_file_envelope(self) -> None:
        f = _forwarder(source="telegram")
        with _patches() as m:
            f._maybe_deliver_to_bot(_payload(content_type="text/markdown"), "artifacts/sub/dir.md", "upsert")

            m.publish_file.assert_called_once_with(
                platform=ConversationSource.TELEGRAM,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                path="artifacts/sub/dir.md",
                filename="dir.md",
                content_type="text/markdown",
            )
            m.spawn.assert_called_once()
            assert f.stats.delivered == 1
            await m.spawned[0]

    async def test_passes_none_content_type_when_missing(self) -> None:
        f = _forwarder(source="whatsapp")
        with _patches() as m:
            f._maybe_deliver_to_bot(_payload(content_type=None), "a.md", "upsert")

            m.publish_file.assert_called_once_with(
                platform=ConversationSource.WHATSAPP,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                path="a.md",
                filename="a.md",
                content_type=None,
            )
            await m.spawned[0]

    async def test_counts_each_delivered_path(self) -> None:
        f = _forwarder(source="telegram")
        with _patches() as m:
            f._maybe_deliver_to_bot(_payload(path="a.md"), "a.md", "upsert")
            f._maybe_deliver_to_bot(_payload(path="b.md"), "b.md", "upsert")

            assert f.stats.delivered == 2  # each new path counts once
            assert m.publish_file.call_count == 2
            assert m.spawn.call_count == 2
            await m.spawned[0]
            await m.spawned[1]


class TestMaybeWarmCache:
    def test_skipped_for_non_upsert_events(self) -> None:
        f = _forwarder()
        with _patches() as m:
            f._maybe_warm_cache(_payload(event="upload"), "a.png", "upload")

        m.spawn.assert_not_called()

    def test_skipped_when_body_inlined(self) -> None:
        f = _forwarder()
        with _patches() as m:
            f._maybe_warm_cache(_payload(body="hello"), "a.md", "upsert")

        m.spawn.assert_not_called()

    async def test_spawns_background_cache_read(self) -> None:
        f = _forwarder()
        with _patches() as m:
            m.resolve_path.return_value = Path("host/a.md")
            f._maybe_warm_cache(_payload(body=None), "artifacts/a.md", "upsert")

            m.spawn.assert_called_once()
            await m.spawned[0]
            m.resolve_path.assert_awaited_once_with(USER_ID, CONVERSATION_ID, "artifacts", "artifacts/a.md")
            m.warm_blocks.assert_called_once_with(Path("host/a.md"))


class TestWarmCache:
    async def test_resolves_path_and_reads_blocks_under_semaphore(self) -> None:
        f = _forwarder()
        with _patches() as m:
            m.resolve_path.return_value = Path("host/a.md")
            await f._warm_cache("artifacts/a.md")

        m.warm_sem.__aenter__.assert_awaited_once()
        m.warm_sem.__aexit__.assert_awaited_once()
        m.resolve_path.assert_awaited_once_with(USER_ID, CONVERSATION_ID, "artifacts", "artifacts/a.md")
        m.warm_blocks.assert_called_once_with(Path("host/a.md"))

    async def test_error_is_swallowed(self) -> None:
        f = _forwarder()
        with _patches() as m:
            m.resolve_path.side_effect = RuntimeError("mount absent")
            await f._warm_cache("a.md")

        m.log.debug.assert_called_once_with(
            "cache warm skipped",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            error="mount absent",
            error_type="RuntimeError",
        )
        m.warm_blocks.assert_not_called()


class TestConsume:
    async def test_skips_foreign_and_malformed_messages(self) -> None:
        f = _forwarder()
        pubsub = _make_pubsub(
            [
                {"type": "subscribe", "data": json.dumps(_payload())},
                {"type": "message", "data": "{not json"},
                _message(_payload(session_id="other-conv")),
                _message(_payload()),
            ]
        )
        with _patches() as m:
            await f._consume(pubsub)

        m.upsert.assert_awaited_once_with(USER_ID, CONVERSATION_ID, _payload())
        m.log.warning.assert_not_called()

    async def test_logs_event_failure_and_continues(self) -> None:
        f = _forwarder()
        pubsub = _make_pubsub(
            [_message(_payload(event="upsert", path="artifacts/a.txt")), _message(_payload(event="remove", path="artifacts/b.txt"))]
        )
        with _patches() as m:
            m.upsert.side_effect = RuntimeError("db down")
            await f._consume(pubsub)

        m.log.warning.assert_called_once_with(
            "event failed",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            error="db down",
            error_type="RuntimeError",
        )
        m.remove_registry.assert_awaited_once_with(USER_ID, CONVERSATION_ID, "artifacts/b.txt")


class TestRun:
    async def test_no_redis_signals_subscribed_and_returns(self) -> None:
        subscribed = asyncio.Event()
        f = _forwarder(subscribed=subscribed)
        with _patches() as m, patch.object(af, "redis_cache", SimpleNamespace(redis=None)):
            await f.run()

        assert subscribed.is_set()
        m.get_registry.assert_not_called()
        m.log.set.assert_not_called()
        m.log.info.assert_not_called()

    async def test_subscribes_loads_registry_and_consumes(self) -> None:
        subscribed = asyncio.Event()
        f = _forwarder(subscribed=subscribed)
        registry = [{"path": "a.txt", "size_bytes": 1, "mtime": 10.0, "content_type": None, "updated_at": "x"}]
        pubsub = _make_pubsub([_message(_payload(event="remove", path="artifacts/b.txt"))])
        fake_redis = MagicMock()
        fake_redis.pubsub.return_value = pubsub
        with _patches() as m, patch.object(af, "redis_cache", SimpleNamespace(redis=fake_redis)):
            m.get_registry.return_value = registry
            await f.run()

        fake_redis.pubsub.assert_called_once_with()
        pubsub.subscribe.assert_awaited_once_with(f"artifacts:{USER_ID}")
        assert subscribed.is_set()
        m.get_registry.assert_awaited_once_with(USER_ID, CONVERSATION_ID)
        m.remove_registry.assert_awaited_once_with(USER_ID, CONVERSATION_ID, "artifacts/b.txt")
        pubsub.unsubscribe.assert_awaited_once_with(f"artifacts:{USER_ID}")
        pubsub.aclose.assert_awaited_once()
        m.log.info.assert_any_call(
            "subscribed",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            registry_mtimes_count=1,
        )
        m.log.info.assert_any_call(
            "closed",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            upserts=0,
            removes=1,
            unchanged=0,
            delivered=0,
        )

    async def test_subscribe_error_is_logged_and_pubsub_closed(self) -> None:
        subscribed = asyncio.Event()
        f = _forwarder(subscribed=subscribed)
        pubsub = _make_pubsub()
        pubsub.subscribe.side_effect = RuntimeError("boom")
        fake_redis = MagicMock()
        fake_redis.pubsub.return_value = pubsub
        with _patches() as m, patch.object(af, "redis_cache", SimpleNamespace(redis=fake_redis)):
            await f.run()

        assert subscribed.is_set()
        m.log.warning.assert_called_once_with(
            "forwarder error",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            error="boom",
            error_type="RuntimeError",
        )
        pubsub.unsubscribe.assert_awaited_once_with(f"artifacts:{USER_ID}")
        pubsub.aclose.assert_awaited_once()

    async def test_registry_load_error_is_logged_and_pubsub_closed(self) -> None:
        subscribed = asyncio.Event()
        f = _forwarder(subscribed=subscribed)
        pubsub = _make_pubsub()
        fake_redis = MagicMock()
        fake_redis.pubsub.return_value = pubsub
        with _patches() as m, patch.object(af, "redis_cache", SimpleNamespace(redis=fake_redis)):
            m.get_registry.side_effect = RuntimeError("mongo down")
            await f.run()

        assert subscribed.is_set()
        pubsub.subscribe.assert_not_awaited()
        m.log.warning.assert_called_once_with(
            "forwarder error",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            error="mongo down",
            error_type="RuntimeError",
        )
        pubsub.aclose.assert_awaited_once()

    async def test_cancellation_propagates_and_closes_pubsub(self) -> None:
        subscribed = asyncio.Event()
        f = _forwarder(subscribed=subscribed)

        async def _infinite() -> AsyncGenerator[dict[str, Any], None]:
            while True:
                yield {"type": "message", "data": "{}"}
                await asyncio.sleep(0)

        pubsub = _make_pubsub()
        pubsub.listen = _infinite
        fake_redis = MagicMock()
        fake_redis.pubsub.return_value = pubsub
        with _patches() as m, patch.object(af, "redis_cache", SimpleNamespace(redis=fake_redis)):
            task = asyncio.create_task(f.run())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert subscribed.is_set()
        pubsub.aclose.assert_awaited_once()
        m.log.info.assert_any_call(
            "closed",
            artifact_log_prefix=ARTIFACT_LOG_PREFIX,
            conversation_id=CONVERSATION_ID,
            upserts=0,
            removes=0,
            unchanged=0,
            delivered=0,
        )


class TestForwardArtifactEvents:
    async def test_delegates_to_forwarder_with_exact_args(self) -> None:
        subscribed = asyncio.Event()
        with patch.object(af, "ArtifactForwarder") as cls_mock:
            instance = cls_mock.return_value
            instance.run = AsyncMock()
            await af.forward_artifact_events(USER_ID, CONVERSATION_ID, STREAM_ID, BOT_MESSAGE_ID, "web", subscribed)

        cls_mock.assert_called_once_with(USER_ID, CONVERSATION_ID, STREAM_ID, BOT_MESSAGE_ID, "web", subscribed)
        instance.run.assert_awaited_once()


class _ChunkedHandle:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.reads: list[int] = []

    def __enter__(self) -> "_ChunkedHandle":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.reads.append(size)
        return self._chunks.pop(0) if self._chunks else b""


class _FakePath:
    def __init__(self, chunks: list[bytes]) -> None:
        self.handle = _ChunkedHandle(chunks)
        self.modes: list[str] = []

    def open(self, mode: str) -> _ChunkedHandle:
        self.modes.append(mode)
        return self.handle
