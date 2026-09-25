"""One browser run all the way through: enqueue, steps with screenshots, handoff, resolve, result.

The journeys in test_browser_task_background.py prove each leg in isolation;
this one proves the legs join up — a run that screenshots its steps, asks the
user to take over mid-run, is told what to do instead, and still reports its
summary at the end, with the conversation's one-browser slot freed.

Fidelity costs, same as the other journeys: no process boundary, no ARQ
serialization, a scripted browser, and a stubbed screenshot store. What this
proves is the production path between those seams: the step cards carry the
screenshot URLs the upload returned (and the bytes reached the upload, not
just the captions), the handoff reaches the user with a live-view link, the
note reaches the agent, and the closing result carries the whole summary.
"""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from app.constants.browser import BrowserSessionStatus
from app.constants.chat import SourceCategory
from app.models.chat_models import ConversationSource
from app.services.browser.jobs import get_conversation_slot
from tests.e2e._harness.browser_job import (
    LIVE_VIEW_LINK,
    SHOT_URL_TEMPLATE,
    JobWorld,
    ScriptedStep,
    browser_job_world,
)
from tests.e2e._harness.graph_run import call, executor_graph, run_graph

pytestmark = pytest.mark.e2e

CONVERSATION = "conv-browser-full-flow"
STREAM = "stream-browser-full-flow"
USER = "user-full-flow"

RETRIEVE = call("retrieve_tools", {"exact_tool_names": ["browser_task"]}, "r1")
START = call("browser_task", {"task": "book a table for two at 7pm"}, "b1")
JOIN = call("wait_for_browser_task", {}, "w1")

NOTE = "skip the login, just tell me the opening hours"
SUMMARY = " ".join(["The table is booked for 7pm on Friday."] * 10)

STEPS = [
    ScriptedStep(
        actions=[("go_to_url", {"url": "https://example.test/book"})],
        outputs=["opened the booking page"],
    ),
    ScriptedStep(
        actions=[("click", {"index": 4})],
        url="https://example.test/confirm",
        outputs=["opened the sign-in wall"],
    ),
    ScriptedStep(actions=[], takeover=("Sign in and come back", "credentials")),
    ScriptedStep(actions=[("input", {"index": 1, "text": "hours"})]),
]


def _configurable(**extra: Any) -> dict[str, Any]:
    return {
        "conversation_id": CONVERSATION,
        "stream_id": STREAM,
        "source_category": SourceCategory.BOT.value,
        "conversation_source": ConversationSource.DISCORD.value,
        **extra,
    }


async def _wait_for_pending_handoff(world: JobWorld) -> str:
    for _ in range(500):
        pending = [
            card
            for card in world.cards()
            if card["kind"] == "handoff" and card["status"] == "pending"
        ]
        if pending:
            return str(pending[0]["handoff_id"])
        await asyncio.sleep(0.01)
    raise AssertionError("the run never asked the user to take over")


async def test_a_full_run_screenshots_hands_off_and_reports() -> None:
    """Enqueue → screenshotted steps → handoff → resolve → result + summary, one run."""
    from app.constants.browser import HandoffDecision, HandoffStatus
    from app.services.browser.handoff import resolve_handoff

    uploads: dict[int, bytes] = {}

    async def _record_upload(png: bytes, conversation_id: str, index: int) -> str | None:
        uploads[index] = png
        return SHOT_URL_TEMPLATE.format(index=index)

    async with browser_job_world(STREAM, steps=STEPS, summary=SUMMARY) as world:
        with patch(
            "app.services.browser.runner.publish_step_screenshot",
            side_effect=_record_upload,
        ):
            async with executor_graph([RETRIEVE, START, JOIN, "Done."]) as graph:
                run_task = asyncio.create_task(
                    run_graph(
                        graph,
                        "book me a table",
                        thread_id=CONVERSATION,
                        user_id=USER,
                        **_configurable(),
                    )
                )
                handoff_id = await _wait_for_pending_handoff(world)
                assert await resolve_handoff(handoff_id, HandoffDecision.CONTINUE, USER, NOTE) == (
                    HandoffStatus.COMPLETED
                )
                run = await run_task
                await world.settle()
        # The conversation can browse again.
        assert await get_conversation_slot(CONVERSATION) is None

    # One job crossed the queue.
    assert len(world.enqueued) == 1

    # The steps reached the upload, not just the captions: real bytes per step.
    assert set(uploads) >= {1, 2}
    assert all(uploads[index] for index in (1, 2))

    # ... and the cards + the bot photos carry the URLs those uploads returned.
    step_cards = [card for card in world.cards() if card["kind"] == "step"]
    assert [card["screenshot"] for card in step_cards[:2]] == [
        SHOT_URL_TEMPLATE.format(index=1),
        SHOT_URL_TEMPLATE.format(index=2),
    ]
    assert all(step_cards[index].get("goal") for index in (0, 1))
    assert world.bot_photos[:2] == [
        SHOT_URL_TEMPLATE.format(index=1),
        SHOT_URL_TEMPLATE.format(index=2),
    ]

    # The handoff asked with a way in, and the note reached the run.
    assert any(LIVE_VIEW_LINK in message for message in world.bot_messages)
    handoffs = [card for card in world.cards() if card["kind"] == "handoff"]
    assert [card["status"] for card in handoffs] == ["pending", "completed"]
    assert world.browser.takeover_notes == [NOTE]

    # The closing result leads with the changed instruction and keeps the whole summary.
    joined = run.result_for("wait_for_browser_task") or ""
    assert joined.startswith("THE USER CHANGED THE REQUEST MID-RUN")
    assert NOTE in joined
    assert SUMMARY in joined

    results = [card for card in world.cards() if card["kind"] == "result"]
    assert [card["status"] for card in results] == [BrowserSessionStatus.COMPLETED.value]
    assert results[0]["summary"] == SUMMARY
    assert results[0]["success"] is True


async def test_every_frame_on_the_stream_is_a_shaped_browser_card() -> None:
    """The frontend renders tool_data by tool_name; a frame without that envelope is a card the stream cannot show."""
    async with browser_job_world(STREAM, steps=STEPS[:2]) as world:
        async with executor_graph([RETRIEVE, START, JOIN, "Done."]) as graph:
            await run_graph(
                graph,
                "book me a table",
                thread_id=CONVERSATION,
                user_id=USER,
                **_configurable(),
            )
            await world.settle()

    frames = world.frames()
    card_frames = [
        frame
        for frame in frames
        if frame.get("tool_data", {}).get("tool_name") == "browser_task_data"
    ]
    assert card_frames, "the run put no cards on the turn's stream"
    for frame in card_frames:
        assert frame["tool_data"]["data"]["kind"] in {
            "session",
            "step",
            "handoff",
            "result",
        }
    assert [frame["tool_data"]["data"]["kind"] for frame in card_frames][0] == "session"
    assert [frame["tool_data"]["data"]["kind"] for frame in card_frames][-1] == "result"
