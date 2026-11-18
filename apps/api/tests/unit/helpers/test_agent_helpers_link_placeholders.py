"""Both graph drivers deliver a reply with its link placeholders swapped for the live links.

A model only ever holds a placeholder (app/services/links/placeholders.py); the
URL must appear in what the user is sent and stored, and the placeholder never
must, however the stream splits it. The live-link read is mocked at the repository seam.
"""

from collections.abc import Iterator
from itertools import pairwise
import json
from typing import Any, Final, cast
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.agents.core.graph_manager import CompiledAgentGraph
from app.config.settings import settings
from app.helpers.agent_helpers import execute_graph_silent, execute_graph_streaming
from app.models.short_link_models import RecordTarget, ShortLink, ShortLinkTargetType
from app.services.links.placeholders import PLACEHOLDER_PREFIX, link_placeholder
from tests.helpers import (
    GraphStreamEvent,
    ScriptedGraph,
    agent_update_event,
    message_chunk_event,
)

OWNER = "u1"
TODO: Final = ShortLinkTargetType.TODO_DELIVERABLE
TOKEN = link_placeholder(RecordTarget(type=TODO, id="t1"))
_CONFIG: Any = {"agent_name": "comms_agent", "configurable": {"user_id": OWNER}}


@pytest.fixture(autouse=True)
def live() -> Iterator[AsyncMock]:
    with patch(
        "app.services.links.placeholders.short_link_repository.get_live_for_target",
        AsyncMock(
            return_value=ShortLink(
                slug="abcdefghijk", user_id=OWNER, target=RecordTarget(type=TODO, id="t1")
            )
        ),
    ) as read:
        yield read


def _url() -> str:
    return f"{settings.SHORTLINK_BASE_URL}/abcdefghijk"


def _reply_in_pieces(reply: str, *cuts: int) -> list[GraphStreamEvent]:
    """Stream reply as chunks cut at the given offsets, then close the node with it."""
    bounds = [0, *cuts, len(reply)]
    chunks = [
        message_chunk_event(message_id="m1", content=reply[start:end])
        for start, end in pairwise(bounds)
    ]
    return [*chunks, agent_update_event(AIMessage(id="m1", content=reply))]


def _streamed(frames: list[str]) -> tuple[str, str]:
    """Return the text the client was sent, and the message stored."""
    sent = []
    stored = ""
    for frame in frames:
        if frame.startswith("nostream: "):
            stored = json.loads(frame.removeprefix("nostream: "))["complete_message"]
        elif frame.startswith("data: {"):
            sent.append(json.loads(frame.removeprefix("data: ")).get("response", ""))
    return "".join(sent), stored


REPLY = f"Done. [Open the plan]({TOKEN}) when you like."


def _graph(*cuts: int) -> CompiledAgentGraph:
    """Script a graph streaming the reply, cut at the given offsets."""
    return cast(CompiledAgentGraph, ScriptedGraph(_reply_in_pieces(REPLY, *cuts)))


@pytest.mark.unit
@pytest.mark.parametrize(
    "cuts",
    [
        (),
        # inside the prefix, inside the token, between the token and its closing paren
        (10, 30, 36),
        (len("Done. [Open the plan](gaia-"), len("Done. [Open the plan](") + len(TOKEN)),
    ],
)
async def test_a_streamed_reply_carries_the_link_never_the_placeholder(
    cuts: tuple[int, ...],
) -> None:
    frames = [f async for f in execute_graph_streaming(_graph(*cuts), {}, _CONFIG)]

    sent, stored = _streamed(frames)
    expected = f"Done. [Open the plan]({_url()}) when you like."
    assert sent == expected
    assert stored == expected
    assert PLACEHOLDER_PREFIX not in "".join(frames)


@pytest.mark.unit
async def test_a_silent_reply_carries_the_link(live: AsyncMock) -> None:
    message, _ = await execute_graph_silent(_graph(12), {}, _CONFIG)

    assert message == f"Done. [Open the plan]({_url()}) when you like."
    live.assert_awaited_with(OWNER, RecordTarget(type=TODO, id="t1"))


@pytest.mark.unit
async def test_a_link_no_longer_live_leaves_its_label(live: AsyncMock) -> None:
    live.return_value = None
    frames = [f async for f in execute_graph_streaming(_graph(25), {}, _CONFIG)]

    assert _streamed(frames) == ("Done. Open the plan when you like.",) * 2


ENDING_IN_LINK = f"Here it is: {TOKEN}"


@pytest.mark.unit
@pytest.mark.parametrize("closed", [True, False])
async def test_a_reply_ending_in_a_placeholder_resolves_when_it_finishes(closed: bool) -> None:
    """The held tail goes out at the node's close, or at the end of a run that never closed it."""
    events = _reply_in_pieces(ENDING_IN_LINK, 5)
    if not closed:
        events = events[:-1]
    frames = [f async for f in execute_graph_streaming(ScriptedGraph(events), {}, _CONFIG)]

    sent, stored = _streamed(frames)
    assert sent == f"Here it is: {_url()}"
    assert stored == sent
