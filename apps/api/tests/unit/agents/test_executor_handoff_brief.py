"""Structured handoff: acceptance_criteria folds into the executor brief.

The comms->executor handoff stays a free-text tool call (backward compatible),
but an acceptance_criteria checklist is composed into the dispatched task as an
explicit definition of done, which the executor loop's completion guard then
holds the executor to. The user's verbatim request rides along separately.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.subagents.subagent_runner import compose_executor_brief
from app.agents.tools.executor_tool import call_executor


class TestComposeTaskBrief:
    def test_no_criteria_returns_task_unchanged(self):
        assert compose_executor_brief("triage my inbox", []) == "triage my inbox"

    def test_blank_criteria_are_ignored(self):
        assert compose_executor_brief("do x", ["  ", ""]) == "do x"

    def test_criteria_become_a_definition_of_done_block(self):
        out = compose_executor_brief(
            "triage my inbox",
            ["promo emails archived", "offer letter flagged"],
        )
        assert out.startswith("triage my inbox")
        assert "Definition of done" in out
        assert "- promo emails archived" in out
        assert "- offer letter flagged" in out

    def test_verbatim_request_rides_along(self):
        out = compose_executor_brief(
            "archive the promos and flag the offer letter",
            ["done"],
            verbatim_request="pls archive the junk mail and flag the offer thing",
        )
        assert out.startswith("Original request (verbatim):\npls archive the junk mail")
        assert "archive the promos and flag the offer letter" in out

    def test_the_brief_layout_is_exact(self):
        """The executor reads this back as its own instructions, so the layout is
        the contract: sections separated by a blank line, criteria one per line.
        Run the criteria together and the definition of done becomes one unreadable
        line the model is asked to satisfy item by item."""
        out = compose_executor_brief(
            "triage my inbox",
            ["promos archived", "offer flagged"],
            verbatim_request="pls sort my mail",
        )

        assert out == (
            "Original request (verbatim):\npls sort my mail"
            "\n\n"
            "triage my inbox"
            "\n\n"
            "Definition of done (every item must be true before you finish):\n"
            "- promos archived\n- offer flagged"
        )


class TestCallExecutorComposition:
    async def test_acceptance_criteria_reach_the_dispatched_task(self):
        """call_executor must dispatch the COMPOSED brief (task + criteria)."""
        config = {"configurable": {"thread_id": "conv-1"}}
        with patch(
            "app.agents.tools.executor_tool._dispatch_executor",
            new=AsyncMock(return_value="Task accepted"),
        ) as mock_dispatch:
            await call_executor.ainvoke(
                {
                    "task": "triage my inbox",
                    "acceptance_criteria": ["promos archived", "important flagged"],
                    "verbatim_request": "please triage my inbox",
                },
                config=config,
            )

        dispatched_task = mock_dispatch.call_args.kwargs["task"]
        assert "triage my inbox" in dispatched_task
        assert "Definition of done" in dispatched_task
        assert "- promos archived" in dispatched_task
        assert "- important flagged" in dispatched_task
        assert "please triage my inbox" in dispatched_task

    async def test_verbatim_request_folds_into_dispatched_task(self):
        config = {"configurable": {"thread_id": "conv-1"}}
        with patch(
            "app.agents.tools.executor_tool._dispatch_executor",
            new=AsyncMock(return_value="Task accepted"),
        ) as mock_dispatch:
            await call_executor.ainvoke(
                {
                    "task": "triage inbox",
                    "acceptance_criteria": ["promos archived"],
                    "verbatim_request": "clear my inbox pls",
                },
                config=config,
            )

        assert (
            "Original request (verbatim):\nclear my inbox pls"
            in mock_dispatch.call_args.kwargs["task"]
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
