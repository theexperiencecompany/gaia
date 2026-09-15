"""What a turn recovered from Redis progress is allowed to contain.

The graph driver decides, per assistant message, whether its text is a reply or
a preamble to a tool call, and announces the verdict as a ``message_boundary``
frame. The live client honours it. The Redis progress record — the thing
``recover_stream_state`` rebuilds a cancelled or errored turn from — used to be
a blind concatenation of every ``response`` frame, so a recovered turn brought
back the working notes the user had been told to drop, glued onto the real
reply with no separator ("…what integrations are available.Working the week
now, Alex"), and two real drafts ran into one bubble.

These tests drive the real dispatcher (``process_data_chunk``) and the real
``StreamManager`` against an in-memory Redis, then run the real recovery.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.cache import STREAM_PROGRESS_PREFIX
from app.constants.general import NEW_MESSAGE_BREAKER
from app.services.chat.chunks import ChunkAccumulators, process_data_chunk
from app.services.chat.state import recover_stream_state
from app.utils.message_breaks import split_message_bubbles

STREAM = "s1"


class _FakeRedisCache:
    """The two operations StreamManager's progress path uses, over a dict."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {
            f"{STREAM_PROGRESS_PREFIX}{STREAM}": {
                "conversation_id": "conv-1",
                "user_id": "u1",
                "complete_message": "",
                "pending_message": "",
                "tool_data": {},
                "is_cancelled": False,
                "is_complete": False,
                "error": None,
            }
        }
        self.redis = MagicMock(
            xadd=AsyncMock(), expire=AsyncMock(), ttl=AsyncMock(return_value=300)
        )

    async def get(self, key: str, *_: Any, **__: Any) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, *_: Any, **__: Any) -> bool:
        self.store[key] = value
        return True


def _response(text: str) -> str:
    return f"data: {json.dumps({'response': text})}\n\n"


def _boundary(message_id: str, *, discarded: bool) -> str:
    payload = {"message_boundary": {"message_id": message_id, "discarded": discarded}}
    return f"data: {json.dumps(payload)}\n\n"


async def _recover(chunks: list[str]) -> str:
    """Feed chunks through the real dispatcher, then recover as persistence would."""
    fake = _FakeRedisCache()
    with patch("app.core.stream_manager.redis_cache", new=fake):
        for chunk in chunks:
            await process_data_chunk(
                STREAM, chunk, ChunkAccumulators({"tool_data": []}, {}, {}, [])
            )
        message, _ = await recover_stream_state(STREAM, "", {"tool_data": []})
    return message


class TestWorkingNotesNeverSurviveRecovery:
    async def test_a_retracted_preamble_is_not_recovered(self) -> None:
        message = await _recover(
            [
                _response("Let me start by gathering context."),
                _boundary("m1", discarded=True),
                _response("Working the week now."),
                _boundary("m2", discarded=False),
            ]
        )

        assert message == "Working the week now."

    async def test_two_kept_drafts_stay_two_bubbles(self) -> None:
        """The second symptom of the same glue: one email draft arriving twice,
        run together as a single paragraph."""
        message = await _recover(
            [
                _response("Here's a clean three-liner."),
                _boundary("m1", discarded=False),
                _response("Here's the cleaned-up version."),
                _boundary("m2", discarded=False),
            ]
        )

        assert split_message_bubbles(message) == [
            "Here's a clean three-liner.",
            "Here's the cleaned-up version.",
        ]


class TestRecoveryStillReturnsWhatTheTurnOwed:
    async def test_text_still_streaming_when_the_turn_stopped_is_kept(self) -> None:
        """A cancelled turn never reaches its boundary. The user watched that
        text arrive, so it is still owed — the driver flushes its own held text
        for the same reason."""
        message = await _recover([_response("Half a sentence")])

        assert message == "Half a sentence"

    async def test_a_settled_reply_plus_a_trailing_fragment_are_separate_bubbles(self) -> None:
        message = await _recover(
            [
                _response("Done."),
                _boundary("m1", discarded=False),
                _response("One more thing"),
            ]
        )

        assert split_message_bubbles(message) == ["Done.", "One more thing"]


async def _recover_from(progress: dict[str, Any]) -> str:
    """Recover from a progress record supplied verbatim, bypassing the writer."""
    with patch(
        "app.services.chat.state.stream_manager.get_progress",
        new=AsyncMock(return_value=progress),
    ):
        message, _ = await recover_stream_state(STREAM, "", {"tool_data": []})
    return message


class TestRecoveringARecordMissingTheBubbleFields:
    """A record written before the settled/pending split is still in Redis under
    its TTL, so recovery supplies both defaults itself. Neither may become text
    the user never saw."""

    async def test_a_record_with_neither_field_recovers_nothing(self) -> None:
        assert await _recover_from({"tool_data": {}}) == ""

    async def test_a_record_with_only_a_trailing_fragment_recovers_just_it(self) -> None:
        assert await _recover_from({"pending_message": "Half a sentence"}) == "Half a sentence"

    async def test_a_record_with_only_settled_bubbles_recovers_just_them(self) -> None:
        assert await _recover_from({"complete_message": "Done."}) == "Done."

    async def test_the_recovered_length_is_logged(self) -> None:
        """The count is how a recovered-but-empty turn is told apart from a turn
        that never wrote progress at all."""
        with patch("app.services.chat.state.log") as mock_log:
            await _recover_from({"complete_message": "Done.", "pending_message": "And one more"})

        assert mock_log.debug.call_args.kwargs == {
            "complete_message_count": len("Done.") + len(NEW_MESSAGE_BREAKER) + len("And one more")
        }
