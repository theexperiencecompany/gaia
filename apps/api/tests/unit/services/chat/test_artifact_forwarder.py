"""Unit tests for ArtifactForwarder's three best-effort except blocks.

Each pipeline step here is deliberately best-effort: a bad event, a failed
persist, or a failed cache warm must never take down the rest of the turn (the
live SSE stream already delivered the card). These tests drive the class's
methods directly with a seam mocked to actually raise, proving the surrounding
except block is reached and swallows the failure instead of propagating it.
"""

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, Mock, patch

import time_machine

from app.services.chat.artifact_forwarder import ArtifactForwarder, _parse_artifact_message
from app.utils.artifact_utils import build_artifact_full_entry, build_artifact_ref_entry


def _forwarder(*, bot_message_id: str | None = "bot-msg-1") -> ArtifactForwarder:
    return ArtifactForwarder(
        user_id="user-1",
        conversation_id="conv-1",
        stream_id="stream-1",
        bot_message_id=bot_message_id,
    )


class _FakePubSub:
    """Yields pre-built pub/sub messages through .listen()."""

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


class TestParseArtifactMessage:
    def test_a_data_frame_for_this_conversation_is_decoded(self) -> None:
        assert _parse_artifact_message(_artifact_message("conv-1", "a.md"), "conv-1") == {
            "session_id": "conv-1",
            "path": "a.md",
            "event": "upsert",
        }

    def test_a_non_message_frame_is_ignored_even_with_a_valid_payload(self) -> None:
        frame = {**_artifact_message("conv-1", "a.md"), "type": "pmessage"}
        assert _parse_artifact_message(frame, "conv-1") is None

    def test_another_conversations_event_is_ignored(self) -> None:
        assert _parse_artifact_message(_artifact_message("conv-2", "a.md"), "conv-1") is None


class TestUpsertPipeline:
    @time_machine.travel(datetime(2026, 10, 1, 9, tzinfo=UTC), tick=False)
    async def test_a_changed_file_is_streamed_registered_and_persisted(self) -> None:
        forwarder = _forwarder()
        payload = {
            "event": "upsert",
            "session_id": "conv-1",
            "path": "a.md",
            "size_bytes": 3,
            "mtime": 2.0,
            "content_type": "text/markdown",
            "body": "abc",
        }
        module = "app.services.chat.artifact_forwarder"
        with (
            patch(f"{module}.stream_manager.publish_chunk", new=AsyncMock()) as publish_chunk,
            patch(f"{module}.upsert_conversation_artifact", new=AsyncMock()) as register,
            patch(
                f"{module}.conversation_repository.append_message_tool_data",
                new=AsyncMock(return_value=True),
            ) as persist,
        ):
            await forwarder._handle_event(payload)

        publish_chunk.assert_awaited_once_with(
            "stream-1",
            "data: " + json.dumps({"tool_data": build_artifact_full_entry(dict(payload))}) + "\n\n",
        )
        register.assert_awaited_once_with("user-1", "conv-1", payload)
        persist.assert_awaited_once_with(
            "conv-1",
            user_id="user-1",
            message_id="bot-msg-1",
            entries=[build_artifact_ref_entry("conv-1", "a.md", "upsert")],
        )
        assert forwarder.registry_mtimes == {"a.md": 2.0}
        assert forwarder.stats.upserts == 1


class TestConsumeSurvivesOneBadEvent:
    async def test_bad_event_is_logged_and_the_loop_continues(self) -> None:
        """One event whose handling raises must not stop the next event from being handled."""
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


class TestPersistEntryIsBestEffort:
    async def test_repository_failure_is_logged_not_raised(self) -> None:
        """A Mongo write failure here must not propagate — the live stream already delivered the card."""
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
        """A missing mount or deleted file during cache warm must degrade to a cold read later, never fail the turn."""
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


class TestBotDeliveryCarriesTheLink:
    async def test_a_bot_file_carries_the_artifacts_heygaia_link(self) -> None:
        """A bot user never sees the web card, so the file message must carry the link."""
        forwarder = ArtifactForwarder(
            user_id="user-1",
            conversation_id="conv-1",
            stream_id="stream-1",
            bot_message_id="bot-msg-1",
            source="telegram",
        )
        payload = {
            "event": "upsert",
            "path": "report.html",
            "content_type": "text/html",
            "short_url": "https://heygaia.link/abcdefghijk",
        }
        with (
            patch(
                "app.services.chat.artifact_forwarder.publish_outbound_file", new=Mock()
            ) as publish,
            patch("app.services.chat.artifact_forwarder.spawn_background_task"),
        ):
            forwarder._maybe_deliver_to_bot(payload, "report.html", "upsert")

        assert publish.call_args.kwargs["caption"] == "https://heygaia.link/abcdefghijk"
