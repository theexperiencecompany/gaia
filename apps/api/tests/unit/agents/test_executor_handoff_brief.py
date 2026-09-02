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

    def test_the_previous_run_folds_in_after_the_task(self):
        out = compose_executor_brief(
            "run the morning briefing",
            ["digest sent"],
            last_run="<last_run>\nat: 2026-08-27T09:00:00+00:00\n</last_run>\n",
        )

        assert out == (
            "run the morning briefing"
            "\n\n"
            "<last_run>\nat: 2026-08-27T09:00:00+00:00\n</last_run>"
            "\n\n"
            "Definition of done (every item must be true before you finish):\n- digest sent"
        )

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


async def _dispatched_brief(tool_args: dict, configurable: dict) -> str:
    """Invoke call_executor and return the brief it handed to _dispatch_executor."""
    with patch(
        "app.agents.tools.executor_tool._dispatch_executor",
        new=AsyncMock(return_value="Task accepted"),
    ) as mock_dispatch:
        await call_executor.ainvoke(tool_args, config={"configurable": configurable})
    return mock_dispatch.call_args.kwargs["task"]


class TestCallExecutorComposition:
    async def test_acceptance_criteria_reach_the_dispatched_task(self):
        """call_executor must dispatch the COMPOSED brief (task + criteria)."""
        dispatched_task = await _dispatched_brief(
            {
                "task": "triage my inbox",
                "acceptance_criteria": ["promos archived", "important flagged"],
            },
            {"thread_id": "conv-1", "user_request": "please triage my inbox"},
        )

        assert "triage my inbox" in dispatched_task
        assert "Definition of done" in dispatched_task
        assert "- promos archived" in dispatched_task
        assert "- important flagged" in dispatched_task
        assert "please triage my inbox" in dispatched_task


class TestVerbatimRequestComesFromTheServer:
    """The verbatim ask is read off configurable, never re-typed by the comms model.

    Routing it through the model made it a model output: asked to emit the full
    task AND re-transcribe a request that may run to MAX_MESSAGE_LENGTH, the
    comms model degenerates — repeating tokens and spilling the schema's own key
    names into `acceptance_criteria`. The server already holds the user's words,
    so the model is no longer asked for them.
    """

    async def test_verbatim_request_folds_in_without_the_model_supplying_it(self):
        dispatched_task = await _dispatched_brief(
            {"task": "triage inbox", "acceptance_criteria": ["promos archived"]},
            {"thread_id": "conv-1", "user_request": "clear my inbox pls"},
        )

        assert dispatched_task.startswith("Original request (verbatim):\nclear my inbox pls")

    async def test_the_model_cannot_supply_a_verbatim_request_at_all(self):
        """The arg is gone from the schema, so a garbled one can never be accepted."""
        assert "verbatim_request" not in call_executor.args

    async def test_a_long_request_is_carried_unclipped(self):
        """`user_messages` is clipped to HIL_JUDGE_MAX_TURN_CHARS (800); the verbatim
        backstop must not be, or long asks — exactly the ones that broke the model —
        silently lose their tail."""
        long_request = "archive the promo from " + ", ".join(
            f"sender{n}@example.com" for n in range(200)
        )
        assert len(long_request) > 800

        dispatched_task = await _dispatched_brief(
            {"task": "triage inbox", "acceptance_criteria": ["promos archived"]},
            {"thread_id": "conv-1", "user_request": long_request},
        )

        assert long_request in dispatched_task

    async def test_absent_user_request_leaves_the_brief_verbatim_free(self):
        """Non-chat roots (workflow triggers) have no literal user turn."""
        dispatched_task = await _dispatched_brief(
            {"task": "triage inbox", "acceptance_criteria": ["promos archived"]},
            {"thread_id": "conv-1"},
        )

        assert "Original request (verbatim)" not in dispatched_task
        assert dispatched_task.startswith("triage inbox")


class TestPreviousRunReachesTheExecutor:
    """A workflow run's checkpoint threads are dropped before it starts, so the
    previous run reaches the worker tier here or not at all."""

    async def test_a_workflow_run_carries_its_previous_run_into_the_brief(self):
        last_run = '<last_run>\nGMAIL_FETCH({"query": "is:unread"})\n</last_run>\n'

        with patch(
            "app.agents.tools.executor_tool.get_last_run_brief",
            new=AsyncMock(return_value=last_run),
        ) as mock_last_run:
            dispatched_task = await _dispatched_brief(
                {"task": "run the briefing", "acceptance_criteria": ["digest sent"]},
                {"thread_id": "conv-1", "workflow_id": "wf-1", "user_id": "u-1"},
            )

        mock_last_run.assert_awaited_once_with("wf-1", "u-1")
        assert '<last_run>\nGMAIL_FETCH({"query": "is:unread"})\n</last_run>' in dispatched_task

    async def test_the_playbook_check_is_asked_about_this_workflow_and_this_user(self):
        """The check reads the workflow's playbook and the user's own run history —
        asked about the wrong one (or about nobody), it answers about a run that
        never happened and the executor writes a playbook from it."""
        with (
            patch(
                "app.agents.tools.executor_tool.get_last_run_brief",
                new=AsyncMock(return_value=""),
            ),
            patch(
                "app.agents.tools.executor_tool.playbook_check_brief",
                new=AsyncMock(return_value=""),
            ) as mock_check,
        ):
            await _dispatched_brief(
                {"task": "run the briefing", "acceptance_criteria": ["digest sent"]},
                {
                    "thread_id": "conv-1",
                    "workflow_id": "wf-1",
                    "user_id": "u-1",
                    "playbook_fallback": "the replay stopped at step 3",
                },
            )

        assert mock_check.await_args.args == ("wf-1", "u-1")
        assert mock_check.await_args.kwargs == {"fallback_note": "the replay stopped at step 3"}

    async def test_an_interactive_chat_turn_never_looks_for_one(self):
        with patch(
            "app.agents.tools.executor_tool.get_last_run_brief", new=AsyncMock(return_value="")
        ) as mock_last_run:
            dispatched_task = await _dispatched_brief(
                {"task": "triage inbox", "acceptance_criteria": ["promos archived"]},
                {"thread_id": "conv-1", "user_id": "u-1"},
            )

        mock_last_run.assert_not_awaited()
        assert "last_run" not in dispatched_task


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
