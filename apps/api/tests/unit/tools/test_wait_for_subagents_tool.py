"""Behavior tests for app/agents/tools/wait_for_subagents_tool.py.

Locks the executor-facing contract of the join: collected subagent results come
back framed in ``<subagent_result agent="...">`` blocks, so the executor can tell
where one subagent's report ends and the next begins, and which agent produced
each. The e2e barrier test drives the same path through real graphs, but only
under live services — this tier runs on every commit.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.wait_for_subagents_tool import wait_for_subagents

MODULE = "app.agents.tools.wait_for_subagents_tool"

CONFIG = {"configurable": {"stream_id": "stream-1", "conversation_id": "conv-1"}}


@pytest.fixture(autouse=True)
def _no_live_work() -> Iterator[None]:
    """Everything the join does before formatting: the dedup marker, the live-task
    poll, the parked-approval loop. Only the collected results matter here."""
    with (
        patch(f"{MODULE}.clear_collection_marker", AsyncMock()),
        patch(f"{MODULE}._poll_live_tasks", AsyncMock()),
        patch(f"{MODULE}._resolve_parked_batch", AsyncMock()),
    ):
        yield


def _collected(results: list[dict[str, str]]) -> object:
    return patch(f"{MODULE}.drain_bg_subagent_results", AsyncMock(return_value=results))


@pytest.mark.unit
class TestCollectedResultFraming:
    async def test_each_result_is_framed_and_attributed_to_its_agent(self) -> None:
        with _collected(
            [
                {"agent": "gmail", "message": "archived 3 promos"},
                {"agent": "slack", "message": "posted to #general"},
            ]
        ):
            collected = await wait_for_subagents.ainvoke({}, CONFIG)

        assert collected == (
            '<subagent_result agent="gmail">\narchived 3 promos\n</subagent_result>\n'
            '<subagent_result agent="slack">\nposted to #general\n</subagent_result>\n'
        )

    async def test_a_result_containing_the_old_separator_stays_one_block(self) -> None:
        """Results used to be joined with a literal ``---``, so a subagent whose
        report contained one split its own result in two as far as the executor
        could tell. The closing tag is what makes the boundary real."""
        report = "found 2 issues\n\n---\n\nboth are stale"

        with _collected([{"agent": "github", "message": report}]):
            collected = await wait_for_subagents.ainvoke({}, CONFIG)

        assert collected == f'<subagent_result agent="github">\n{report}\n</subagent_result>\n'

    async def test_no_results_says_so_in_plain_words(self) -> None:
        with _collected([]):
            collected = await wait_for_subagents.ainvoke({}, CONFIG)

        assert collected == "No background subagent results to collect."
