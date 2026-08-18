"""Unit tests for ArtifactForwarder's best-effort except blocks and its dedup.

Each pipeline step here is deliberately best-effort: a bad event, a failed
persist, or a failed cache warm must never take down the rest of the turn (the
live SSE stream already delivered the card). These tests drive the class's
methods directly with a seam mocked to actually raise, proving the surrounding
except block is reached and swallows the failure instead of propagating it.

The dedup tests at the bottom cover the other half of the class: the per-turn
``path → mtime`` map, whose whole job is to make a re-emit of an unchanged file
free.
"""

from unittest.mock import AsyncMock, patch

from app.services.chat.artifact_forwarder import ArtifactForwarder
from app.utils.artifact_utils import build_artifact_ref_entry

MODULE = "app.services.chat.artifact_forwarder"


def _forwarder(
    *, bot_message_id: str | None = "bot-msg-1", source: str | None = None
) -> ArtifactForwarder:
    return ArtifactForwarder(
        user_id="user-1",
        conversation_id="conv-1",
        stream_id="stream-1",
        bot_message_id=bot_message_id,
        source=source,
    )


class _FakePubSub:
    """Yields pre-built pub/sub messages through ``.listen()``."""

    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    async def listen(self):
        for message in self._messages:
            yield message


def _artifact_message(conversation_id: str, path: str) -> dict[str, str]:
    return {
        "type": "message",
        "data": f'{{"session_id": "{conversation_id}", "path": "{path}", "event": "upsert"}}',
    }


class TestConsumeSurvivesOneBadEvent:
    async def test_bad_event_is_logged_and_the_loop_continues(self) -> None:
        """One event whose handling raises must not stop the next event from
        being handled — the whole point of the per-event try/except."""
        forwarder = _forwarder()
        pubsub = _FakePubSub(
            [
                _artifact_message("conv-1", "bad.txt"),
                _artifact_message("conv-1", "good.txt"),
            ]
        )

        with (
            patch.object(
                forwarder,
                "_handle_event",
                new=AsyncMock(side_effect=[RuntimeError("boom"), None]),
            ) as mock_handle,
            patch("app.services.chat.artifact_forwarder.log") as mock_log,
        ):
            await forwarder._consume(pubsub)  # must not raise

        assert mock_handle.await_count == 2  # the second payload was still processed
        mock_log.warning.assert_called_once()


class TestParseArtifactMessage:
    """`_parse_artifact_message` runs *outside* `_consume`'s per-event try/except,
    so anything it raises kills the forwarder for the whole turn rather than
    dropping one message."""

    async def test_a_message_for_another_conversation_is_dropped(self) -> None:
        forwarder = _forwarder()
        pubsub = _FakePubSub([_artifact_message("conv-2", "other.txt")])

        with patch.object(forwarder, "_handle_event", new=AsyncMock()) as mock_handle:
            await forwarder._consume(pubsub)

        mock_handle.assert_not_awaited()


class TestPersistEntryIsBestEffort:
    async def test_repository_failure_is_logged_not_raised(self) -> None:
        """A Mongo write failure on the reload-durability path must not
        propagate — the live stream already delivered the card to the user."""
        forwarder = _forwarder(bot_message_id="bot-msg-1")
        entry = build_artifact_ref_entry("conv-1", "report.pdf", "upsert")

        with (
            patch("app.services.chat.artifact_forwarder.conversation_repository") as mock_repo,
            patch("app.services.chat.artifact_forwarder.log") as mock_log,
        ):
            mock_repo.append_message_tool_data = AsyncMock(side_effect=RuntimeError("mongo down"))
            await forwarder._persist_entry(entry)  # must not raise

        mock_log.warning.assert_called_once()


class TestWarmCacheIsBestEffort:
    async def test_resolve_session_path_failure_is_logged_not_raised(self) -> None:
        """A missing mount / deleted file during cache warm must degrade to a
        cold read later, never fail the turn."""
        forwarder = _forwarder()

        with (
            patch(
                "app.services.chat.artifact_forwarder.resolve_session_path",
                new=AsyncMock(side_effect=OSError("mount missing")),
            ),
            patch("app.services.chat.artifact_forwarder.log") as mock_log,
        ):
            await forwarder._warm_cache("report.pdf")  # must not raise

        mock_log.debug.assert_called_once()


class TestDedupOfArtifactsWithNoMtime:
    """An artifact whose event carries no mtime must still dedup.

    The map is the only thing standing between a whole-dir re-emit and a
    re-publish per event: a miss re-streams the card, rewrites the Mongo
    registry, and re-delivers the file to the bot. Normalising the stored side
    ("unknown" → 0.0) while comparing against the payload's raw value (None)
    makes every such event a miss, forever.
    """

    async def test_a_stored_row_with_no_mtime_dedups_against_an_mtime_less_event(self) -> None:
        # Rows written before mtime was stamped hold `mtime: null`; the event that
        # re-emits them carries no mtime either. Same file, same nothing — a skip.
        forwarder = _forwarder()
        with patch(
            f"{MODULE}.get_conversation_artifacts",
            new=AsyncMock(return_value=[{"path": "report.pdf", "mtime": None}]),
        ):
            await forwarder._load_registry()

        await forwarder._handle_event({"path": "report.pdf", "event": "upsert"})

        assert forwarder.stats.unchanged == 1
        assert forwarder.stats.upserts == 0

    async def test_an_mtime_less_file_is_published_once_per_turn_not_once_per_event(self) -> None:
        # The same file re-emitted within the turn: the first event publishes and
        # seeds the map, the second must hit it.
        forwarder = _forwarder()
        payload: dict[str, object] = {"path": "report.pdf", "event": "upsert"}
        with (
            patch(f"{MODULE}.stream_manager") as stream,
            patch(f"{MODULE}.upsert_conversation_artifact", new=AsyncMock()),
            patch(f"{MODULE}.conversation_repository") as repository,
            patch(f"{MODULE}.spawn_background_task"),
        ):
            stream.publish_chunk = AsyncMock()
            repository.append_message_tool_data = AsyncMock()
            await forwarder._handle_event(payload)
            await forwarder._handle_event(payload)

        assert (forwarder.stats.upserts, forwarder.stats.unchanged) == (1, 1)

    async def test_a_changed_file_is_still_republished(self) -> None:
        # The dedup must not swallow a real edit: a new mtime is a new card.
        forwarder = _forwarder()
        with patch(
            f"{MODULE}.get_conversation_artifacts",
            new=AsyncMock(return_value=[{"path": "report.pdf", "mtime": 100.0}]),
        ):
            await forwarder._load_registry()

        with (
            patch(f"{MODULE}.stream_manager") as stream,
            patch(f"{MODULE}.upsert_conversation_artifact", new=AsyncMock()),
            patch(f"{MODULE}.conversation_repository") as repository,
            patch(f"{MODULE}.spawn_background_task"),
        ):
            stream.publish_chunk = AsyncMock()
            repository.append_message_tool_data = AsyncMock()
            await forwarder._handle_event({"path": "report.pdf", "event": "upsert", "mtime": 200.0})

        assert (forwarder.stats.upserts, forwarder.stats.unchanged) == (1, 0)

    async def test_an_unedited_file_dedups_against_its_stored_mtime(self) -> None:
        # The counterpart of the test above, and the case both sides of the
        # comparison have to read the same key to get right: same file, same
        # mtime, so the re-emit is free.
        forwarder = _forwarder()
        with patch(
            f"{MODULE}.get_conversation_artifacts",
            new=AsyncMock(return_value=[{"path": "report.pdf", "mtime": 100.0}]),
        ):
            await forwarder._load_registry()
        assert forwarder.registry_mtimes == {"report.pdf": 100.0}

        # Twice: the skip counter is per event, not a "did any skip happen" flag —
        # it is what tells us how much a whole-dir re-emit actually costs.
        await forwarder._handle_event({"path": "report.pdf", "event": "upsert", "mtime": 100.0})
        await forwarder._handle_event({"path": "report.pdf", "event": "upsert", "mtime": 100.0})

        assert (forwarder.stats.upserts, forwarder.stats.unchanged) == (0, 2)

    async def test_publishing_records_the_events_mtime_so_the_next_one_dedups(self) -> None:
        # Nothing is preloaded here: the first event both publishes and seeds the
        # map, so a wrong value written on publish only shows up as the identical
        # second event being published all over again.
        forwarder = _forwarder()
        payload: dict[str, object] = {"path": "report.pdf", "event": "upsert", "mtime": 100.0}
        with (
            patch(f"{MODULE}.stream_manager") as stream,
            patch(f"{MODULE}.upsert_conversation_artifact", new=AsyncMock()),
            patch(f"{MODULE}.conversation_repository") as repository,
            patch(f"{MODULE}.spawn_background_task"),
        ):
            stream.publish_chunk = AsyncMock()
            repository.append_message_tool_data = AsyncMock()
            await forwarder._handle_event(payload)
            assert forwarder.registry_mtimes == {"report.pdf": 100.0}
            await forwarder._handle_event(dict(payload))

        assert (forwarder.stats.upserts, forwarder.stats.unchanged) == (1, 1)


class TestBotDelivery:
    """A bot user never sees the SSE card, so the outbound queue is the only way
    the file reaches them — and the envelope it carries is what the bot uploads."""

    async def test_the_events_content_type_reaches_the_outbound_envelope(self) -> None:
        # The bot uploads the artifact with the MIME type in the envelope; losing it
        # turns an image into an unopenable octet-stream attachment.
        forwarder = _forwarder(source="telegram")
        payload: dict[str, object] = {
            "path": "out/chart.png",
            "event": "upsert",
            "content_type": "image/png",
        }
        with (
            patch(f"{MODULE}.stream_manager") as stream,
            patch(f"{MODULE}.upsert_conversation_artifact", new=AsyncMock()),
            patch(f"{MODULE}.conversation_repository") as repository,
            patch(f"{MODULE}.spawn_background_task"),
            patch(f"{MODULE}.publish_outbound_file") as publish,
        ):
            stream.publish_chunk = AsyncMock()
            repository.append_message_tool_data = AsyncMock()
            await forwarder._handle_event(payload)

        assert publish.call_args.kwargs["content_type"] == "image/png"
        assert publish.call_args.kwargs["filename"] == "chart.png"


class TestRemoveEventRouting:
    """`remove` is the one event that must not go down the publish path: the file
    is gone, so re-streaming a card for it would leave the user a dead link."""

    async def test_a_remove_event_drops_the_file_instead_of_publishing_it(self) -> None:
        forwarder = _forwarder()
        with patch(
            f"{MODULE}.get_conversation_artifacts",
            new=AsyncMock(return_value=[{"path": "report.pdf", "mtime": 100.0}]),
        ):
            await forwarder._load_registry()

        with (
            patch(f"{MODULE}.stream_manager") as stream,
            patch(f"{MODULE}.remove_conversation_artifact", new=AsyncMock()) as remove_row,
            patch(f"{MODULE}.conversation_repository") as repository,
        ):
            stream.publish_chunk = AsyncMock()
            repository.append_message_tool_data = AsyncMock()
            await forwarder._handle_event({"path": "report.pdf", "event": "remove"})

        assert (forwarder.stats.removes, forwarder.stats.upserts) == (1, 0)
        assert forwarder.registry_mtimes == {}
        remove_row.assert_awaited_once()
