"""Structured handoff: acceptance_criteria folds into the executor brief.

The comms->executor handoff stays a free-text tool call (backward compatible),
but an optional acceptance_criteria checklist is composed into the dispatched
task as an explicit definition of done, which the executor loop's completion
guard then holds the executor to.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.executor_tool import _compose_task_brief, call_executor


class TestComposeTaskBrief:
    def test_no_criteria_returns_task_unchanged(self):
        assert _compose_task_brief("triage my inbox", []) == "triage my inbox"

    def test_blank_criteria_are_ignored(self):
        assert _compose_task_brief("do x", ["  ", ""]) == "do x"

    def test_criteria_become_a_definition_of_done_block(self):
        out = _compose_task_brief(
            "triage my inbox",
            ["promo emails archived", "offer letter flagged"],
        )
        assert out.startswith("triage my inbox")
        assert "Definition of done" in out
        assert "- promo emails archived" in out
        assert "- offer letter flagged" in out


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
                },
                config=config,
            )

        dispatched_task = mock_dispatch.call_args.kwargs["task"]
        assert "triage my inbox" in dispatched_task
        assert "Definition of done" in dispatched_task
        assert "- promos archived" in dispatched_task
        assert "- important flagged" in dispatched_task

    async def test_backward_compatible_without_criteria(self):
        """Omitting acceptance_criteria dispatches the plain task, unchanged."""
        config = {"configurable": {"thread_id": "conv-1"}}
        with patch(
            "app.agents.tools.executor_tool._dispatch_executor",
            new=AsyncMock(return_value="Task accepted"),
        ) as mock_dispatch:
            await call_executor.ainvoke({"task": "what can you do?"}, config=config)

        assert mock_dispatch.call_args.kwargs["task"] == "what can you do?"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
