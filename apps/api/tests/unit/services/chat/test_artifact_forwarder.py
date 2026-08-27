"""Unit tests for ArtifactForwarder's three best-effort except blocks.

Each pipeline step here is deliberately best-effort: a bad event, a failed
persist, or a failed cache warm must never take down the rest of the turn (the
live SSE stream already delivered the card). These tests drive the class's
methods directly with a seam mocked to actually raise, proving the surrounding
except block is reached and swallows the failure instead of propagating it.
"""

from unittest.mock import AsyncMock, patch

from app.services.chat.artifact_forwarder import ArtifactForwarder
from app.utils.artifact_utils import build_artifact_ref_entry


def _forwarder(*, bot_message_id: str | None = "bot-msg-1") -> ArtifactForwarder:
    return ArtifactForwarder(
        user_id="user-1",
        conversation_id="conv-1",
        stream_id="stream-1",
        bot_message_id=bot_message_id,
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
