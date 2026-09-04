"""What the saved turn must contain, so a reload shows what the user watched.

The live turn and the reloaded turn are assembled by two different
implementations — the browser folds SSE frames through
``libs/shared/ts/src/chat/turnAccumulator.ts``, while the server builds the
persisted message in ``app/services/chat/`` and ``app/utils/stream_utils.py``.
Nothing forces them to agree, so a divergence ships as "it looked right until I
refreshed" with no failing test anywhere.

These tests run the real persist path (``_persist_turn`` →
``save_conversation_async``) and assert on the ``MessageModel`` that would reach
Mongo. Only the DB write (``update_messages``) and the Redis progress read
(``recover_stream_state``) are mocked — everything that shapes the message is real.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.chat import EMPTY_RESPONSE_FALLBACK
from app.models.chat_models import MessageModel
from app.models.message_models import MessageRequestWithHistory
from app.services.chat import stream as chat_stream
from app.services.chat.chunks import process_data_chunk
from app.services.chat.state import merge_tool_outputs
from app.services.chat.stream import _persist_turn, _StreamState

USER = {"user_id": "u1", "email": "u1@test.local"}
CONV = "conv-1"


def _body(message: str = "what's on my calendar?") -> MessageRequestWithHistory:
    return MessageRequestWithHistory(
        message=message,
        conversation_id=CONV,
        messages=[{"role": "user", "content": message}],
    )


async def persist(state: _StreamState) -> tuple[MessageModel, list[str]]:
    """Run the real persist path; return the saved bot message and what it published."""
    published: list[str] = []
    sm = AsyncMock()
    sm.publish_chunk = AsyncMock(side_effect=lambda _sid, c: published.append(c))

    with (
        patch.object(
            chat_stream,
            "recover_stream_state",
            new=AsyncMock(side_effect=lambda _sid, msg, td: (msg, td)),
        ),
        patch.object(chat_stream, "stream_manager", sm),
        patch("app.services.chat.persistence.update_messages", new_callable=AsyncMock) as update,
    ):
        await _persist_turn("s1", _body(), USER, CONV, state)

    request = update.await_args.args[0]
    bot = next(m for m in request.messages if m.type == "bot")
    return bot, published


class TestFollowUpActions:
    async def test_follow_up_chips_survive_the_save(self):
        """The chips render live off a ``follow_up_actions`` frame. If the turn
        is saved without them, they vanish on reload, on a sync, and on any
        second device — the message is there, the chips are not.
        """
        state = _StreamState()
        state.complete_message = "You have two meetings."
        state.follow_up_actions = ["Draft a reply", "Add to calendar"]

        bot, _ = await persist(state)

        assert bot.follow_up_actions == ["Draft a reply", "Add to calendar"]

    async def test_a_turn_with_no_chips_saves_none_not_an_empty_list(self):
        """Control, and a shape guard: the client distinguishes "no suggestions"
        from "suggestions not computed" (``syncService`` writes
        ``follow_up_actions ?? null``)."""
        state = _StreamState()
        state.complete_message = "Done."

        bot, _ = await persist(state)

        assert bot.follow_up_actions is None


class TestPersistedTurnMatchesTheLiveStream:
    """The persisted entry must reproduce what the browser assembled live.

    The frontend receives a tool call and its result as two separate frames and
    joins them by ``tool_call_id`` (``mergeToolOutputIntoToolData``). The server
    does the same join server-side via ``merge_tool_outputs``. These two must
    land on the same shape or the reloaded card differs from the live one.
    """

    async def _run_turn(self, chunks: list[dict[str, Any]]) -> tuple[list[str], _StreamState]:
        """Feed chunks through the real dispatcher, capturing what was published."""
        published: list[str] = []
        state = _StreamState()

        sm = AsyncMock()
        sm.publish_chunk = AsyncMock(side_effect=lambda _sid, c: published.append(c))
        sm.update_progress = AsyncMock()

        with (
            patch("app.services.chat.chunks.stream_manager", sm),
            patch("app.utils.stream_publishers.stream_manager", sm),
        ):
            for chunk in chunks:
                state.follow_up_actions, _ = await process_data_chunk(
                    "s1",
                    f"data: {json.dumps(chunk)}\n\n",
                    state.tool_data,
                    state.tool_outputs,
                    state.todo_progress_accumulated,
                    state.follow_up_actions,
                )
        return published, state

    async def test_every_streamed_tool_card_is_also_accumulated_for_the_save(self):
        """``publish_tool_data`` appends and publishes from one variable — the
        single point where live and persisted must agree. Nothing compared them
        before this test."""
        published, state = await self._run_turn(
            [
                {
                    "tool_data": {
                        "tool_name": "tool_calls_data",
                        "data": {"tool_name": "GMAIL_FETCH_MESSAGES", "tool_call_id": "tc-1"},
                    }
                },
                {
                    "tool_data": {
                        "tool_name": "tool_calls_data",
                        "data": {"tool_name": "add_memory", "tool_call_id": "tc-2"},
                    }
                },
            ]
        )

        streamed = [json.loads(c[6:-2])["tool_data"] for c in published if '"tool_data"' in c]
        assert streamed == state.tool_data["tool_data"]

    async def test_the_saved_card_carries_the_result_the_client_joined_live(self):
        """Live, the client merges the ``tool_output`` frame onto the card by
        ``tool_call_id``. The save must reach the same place, or the reloaded
        card shows a tool that never returned."""
        published, state = await self._run_turn(
            [
                {
                    "tool_data": {
                        "tool_name": "tool_calls_data",
                        "data": {"tool_name": "GMAIL_FETCH_MESSAGES", "tool_call_id": "tc-1"},
                    }
                },
                {"tool_output": {"tool_call_id": "tc-1", "output": "3 unread"}},
            ]
        )
        merge_tool_outputs(state.tool_data, state.tool_outputs)

        # What the client saw: a card frame plus an output frame carrying the id.
        outputs = [json.loads(c[6:-2])["tool_output"] for c in published if '"tool_output"' in c]
        assert outputs == [{"tool_call_id": "tc-1", "output": "3 unread"}]
        # What gets saved: the same result, already joined onto the card.
        assert state.tool_data["tool_data"][0]["data"]["output"] == "3 unread"

    async def test_an_output_for_an_unknown_call_is_not_grafted_onto_a_card(self):
        """The join is by id on both sides. A positional or last-wins merge
        would attach one tool's result to another tool's card."""
        _, state = await self._run_turn(
            [
                {
                    "tool_data": {
                        "tool_name": "tool_calls_data",
                        "data": {"tool_name": "add_memory", "tool_call_id": "tc-1"},
                    }
                },
                {"tool_output": {"tool_call_id": "tc-other", "output": "orphan"}},
            ]
        )
        merge_tool_outputs(state.tool_data, state.tool_outputs)

        assert "output" not in state.tool_data["tool_data"][0]["data"]


class TestArtifactLinksSurviveTheSave:
    async def test_a_relative_artifact_path_is_absolutized_against_this_conversation(self):
        """The agent writes ``./artifacts/<name>``, which is right inside the
        sandbox and a dead link from the browser. The rewrite needs THIS
        conversation's id — without it the saved message keeps the relative
        path and every image in the turn renders broken on reload."""
        state = _StreamState()
        state.complete_message = "here's the chart: ./artifacts/chart.png"

        bot, _ = await persist(state)

        assert f"/sessions/{CONV}/artifacts/chart.png" in bot.response
        assert "./artifacts/chart.png" not in bot.response


class TestAnEmptyCompletionIsNeverSaved:
    """41 empty bot messages across 14 production conversations came through
    here: the model returned no text, nothing errored, and ``_persist_turn``
    wrote the empty string as the turn. Every renderer drops an empty body
    silently (the bot adapter's ``deliverBubble`` returns early on falsy text),
    so the user saw nothing and resent the same message.
    """

    @pytest.mark.regression
    async def test_a_model_that_returned_no_text_is_saved_as_one_honest_line(self):
        state = _StreamState()
        state.complete_message = ""

        bot, _ = await persist(state)

        assert bot.response == EMPTY_RESPONSE_FALLBACK

    @pytest.mark.regression
    async def test_the_fallback_line_is_also_streamed_so_the_live_turn_is_not_silent(self):
        """Persisting it is not enough — the user watching the stream has to see
        something before the turn closes, or they resend before any reload."""
        state = _StreamState()
        state.complete_message = ""

        _, published = await persist(state)

        assert any(EMPTY_RESPONSE_FALLBACK in chunk for chunk in published)

    async def test_a_whitespace_only_completion_counts_as_empty(self):
        state = _StreamState()
        state.complete_message = "\n  \n"

        bot, _ = await persist(state)

        assert bot.response == EMPTY_RESPONSE_FALLBACK

    async def test_a_failed_turn_keeps_its_error_text_and_gains_no_fallback(self):
        """The error path already streamed an ``ErrorFrame`` and persists the
        same text — adding "say it again?" on top would contradict it."""
        state = _StreamState()
        state.complete_message = ""
        state.error = "Something went wrong while generating this response (TimeoutError)."

        bot, published = await persist(state)

        assert bot.response == ""
        assert bot.error == state.error
        assert published == []

    async def test_a_cancelled_turn_is_not_answered_with_say_it_again(self):
        """The user stopped this turn on purpose; nothing failed to come through."""
        state = _StreamState()
        state.complete_message = ""
        state.is_cancelled = True

        bot, published = await persist(state)

        assert bot.response == ""
        assert published == []

    async def test_a_turn_whose_content_is_tool_cards_is_left_alone(self):
        """An image or a card with no prose is a real answer, not silence."""
        state = _StreamState()
        state.complete_message = ""
        state.tool_data = {
            "tool_data": [{"tool_name": "image_tool", "data": {"url": "http://x/y.png"}}]
        }

        bot, published = await persist(state)

        assert bot.response == ""
        assert published == []
