"""Unit tests for ArtifactForwarder's three best-effort except blocks.

Each pipeline step here is deliberately best-effort: a bad event, a failed
persist, or a failed cache warm must never take down the rest of the turn (the
live SSE stream already delivered the card). These tests drive the class's
methods directly with a seam mocked to actually raise, proving the surrounding
except block is reached and swallows the failure instead of propagating it.
"""

import json
from typing import Literal, cast
from unittest.mock import AsyncMock, patch

from redis.asyncio.client import PubSub

from app.models.chat_models import ConversationSource
from app.services.artifact_events import ArtifactFileEvent
from app.services.chat.artifact_forwarder import (
    ArtifactForwarder,
    _parse_artifact_message,
    _PubSubMessage,
)
from app.services.outbox.models import NoticeOutcome, NoticeReport, ProducerKind
from app.utils.artifact_utils import build_artifact_ref_entry


def _forwarder(*, bot_message_id: str | None = "bot-msg-1") -> ArtifactForwarder:
    return ArtifactForwarder(
        user_id="user-1",
        conversation_id="conv-1",
        stream_id="stream-1",
        bot_message_id=bot_message_id,
    )


def _file_event(
    path: str,
    *,
    mtime: float = 1.0,
    event: Literal["upsert", "upload"] = "upsert",
    content_type: str | None = None,
) -> ArtifactFileEvent:
    return {
        "event": event,
        "session_id": "conv-1",
        "path": path,
        "size_bytes": 10,
        "mtime": mtime,
        "content_type": content_type,
    }


def _artifact_message(conversation_id: str, path: str) -> _PubSubMessage:
    return {
        "type": "message",
        "data": json.dumps({**_file_event(path), "session_id": conversation_id}),
    }


class _FakePubSub:
    """Yields pre-built pub/sub messages through .listen()."""

    def __init__(self, messages: list[_PubSubMessage]) -> None:
        self._messages = messages

    async def listen(self):
        for message in self._messages:
            yield message


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
            await forwarder._consume(cast(PubSub, pubsub))  # must not raise

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


def _bot_forwarder() -> ArtifactForwarder:
    return ArtifactForwarder(
        user_id="user-1",
        conversation_id="conv-1",
        stream_id="stream-1",
        bot_message_id=None,
        source=ConversationSource.TELEGRAM.value,
    )


class TestBotDelivery:
    """A file the agent writes for a bot user reaches them through the outbox, once, by reference."""

    async def test_an_agent_written_file_is_submitted_as_an_artifact_notice(self) -> None:
        payload = _file_event("out/report.pdf", mtime=12.5, content_type="application/pdf")
        with patch("app.services.chat.artifact_forwarder.submit", new=AsyncMock()) as submit:
            await _bot_forwarder()._maybe_deliver_to_bot(payload, "out/report.pdf", "upsert")

        report = submit.await_args.args[0]
        assert (report.producer, report.outcome) == (ProducerKind.ARTIFACT, NoticeOutcome.INFO)
        assert (report.recipient, report.subject.owner_conversation_id) == ("user-1", "conv-1")
        [artifact] = report.artifacts
        assert (artifact.conversation_id, artifact.path, artifact.filename) == (
            "conv-1",
            "out/report.pdf",
            "report.pdf",
        )
        assert artifact.content_type == "application/pdf"
        assert artifact.url is None

    async def test_a_file_is_submitted_once_per_turn(self) -> None:
        forwarder = _bot_forwarder()
        with patch("app.services.chat.artifact_forwarder.submit", new=AsyncMock()) as submit:
            await forwarder._maybe_deliver_to_bot(_file_event("a.txt"), "a.txt", "upsert")
            await forwarder._maybe_deliver_to_bot(
                _file_event("a.txt", mtime=2.0), "a.txt", "upsert"
            )
        submit.assert_awaited_once()

    async def test_a_changed_file_in_a_later_turn_is_a_new_report(self) -> None:
        reports: list[NoticeReport] = []
        with patch(
            "app.services.chat.artifact_forwarder.submit",
            new=AsyncMock(side_effect=reports.append),
        ):
            await _bot_forwarder()._maybe_deliver_to_bot(_file_event("a.txt"), "a.txt", "upsert")
            await _bot_forwarder()._maybe_deliver_to_bot(
                _file_event("a.txt", mtime=2.0), "a.txt", "upsert"
            )
        assert reports[0].report_id != reports[1].report_id

    async def test_a_user_upload_is_not_sent_back_to_them(self) -> None:
        with patch("app.services.chat.artifact_forwarder.submit", new=AsyncMock()) as submit:
            await _bot_forwarder()._maybe_deliver_to_bot(
                _file_event("a.txt", event="upload"), "a.txt", "upload"
            )
        submit.assert_not_awaited()

    async def test_a_web_turn_is_never_submitted(self) -> None:
        with patch("app.services.chat.artifact_forwarder.submit", new=AsyncMock()) as submit:
            await _forwarder()._maybe_deliver_to_bot(_file_event("a.txt"), "a.txt", "upsert")
        submit.assert_not_awaited()


class TestParseArtifactMessage:
    def test_an_event_for_this_conversation_is_parsed(self) -> None:
        event = _parse_artifact_message(_artifact_message("conv-1", "a.txt"), "conv-1")
        assert event is not None
        assert event["path"] == "a.txt"

    def test_an_event_for_another_conversation_is_dropped(self) -> None:
        assert _parse_artifact_message(_artifact_message("conv-2", "a.txt"), "conv-1") is None

    def test_a_frame_that_is_not_a_message_is_dropped(self) -> None:
        assert _parse_artifact_message({"type": "subscribe"}, "conv-1") is None

    def test_a_data_frame_that_is_not_an_artifact_event_is_logged_and_dropped(self) -> None:
        with patch("app.services.chat.artifact_forwarder.log") as mock_log:
            parsed = _parse_artifact_message({"type": "message", "data": "{not json"}, "conv-1")
        assert parsed is None
        mock_log.warning.assert_called_once()
