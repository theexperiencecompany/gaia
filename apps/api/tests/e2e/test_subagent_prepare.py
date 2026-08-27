"""Preparing one subagent for execution.

``prepare_subagent_execution`` is the single path both the executor's ``handoff``
tool and the dev direct-invocation endpoint go through to turn "run gmail on
this task" into a runnable context. Its failure branches are covered through
``_resolve_subagent``; the function itself had no test at all, so nothing pinned
what it builds on the way out — the checkpoint thread a subagent resumes on, the
task text the model is handed, or the identity a provider tool authenticates as.

External I/O is doubled at the module boundary (``handoff_tools`` imports every
collaborator by name, so patching there is what takes effect); everything the
assertions cover is real.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.core.subagents import handoff_tools
from app.agents.core.subagents.handoff_tools import prepare_subagent_execution

pytestmark = pytest.mark.e2e

CONV_THREAD = "conv-abc"


def _configurable(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "user_id": "u1",
        "email": "u1@test.local",
        "user_name": "Dhruv",
        "thread_id": CONV_THREAD,
    }
    base.update(overrides)
    return base


@pytest.fixture
def gmail_subagent(monkeypatch: pytest.MonkeyPatch):
    """Resolve to a stand-in gmail subagent without Mongo, OAuth or Composio.

    ``_resolve_subagent`` is a separately-tested concern (every one of its
    failure branches is covered in ``test_handoff_tools``); doubling it here
    keeps these tests on what preparation *builds*.
    """
    graph = MagicMock(name="gmail_graph")
    monkeypatch.setattr(
        handoff_tools,
        "_resolve_subagent",
        AsyncMock(return_value=(graph, "gmail_agent", "gmail", False)),
    )
    monkeypatch.setattr(
        handoff_tools,
        "create_subagent_system_message",
        AsyncMock(return_value=SystemMessage(content="You are the gmail agent.")),
    )
    monkeypatch.setattr(
        handoff_tools, "_build_integration_metadata", AsyncMock(return_value={"name": "Gmail"})
    )
    monkeypatch.setattr(
        handoff_tools,
        "get_subagent_by_id",
        lambda _id: MagicMock(provider="gmail", name="Gmail"),
    )
    monkeypatch.setattr(
        handoff_tools,
        "get_provider_metadata",
        AsyncMock(return_value={"username": "dhruv@gmail.com"}),
    )
    # The context message pulls memories, skills and stored instructions; each is
    # its own subsystem and none of them is what this file is about.
    monkeypatch.setattr(
        "app.agents.core.subagents.subagent_runner.assemble_context",
        AsyncMock(
            return_value=AssembledContext(
                stable=SystemMessage(
                    content="dynamic context", additional_kwargs={"dynamic_context": True}
                ),
                volatile=None,
            )
        ),
    )
    return graph


def _task_message(ctx: Any) -> HumanMessage:
    """The task turn, picked by its ``visible_to`` marker.

    ``build_initial_messages`` also puts the current time in a HumanMessage (to
    keep the system prefix byte-stable for the prompt cache), so position is not
    a safe way to find the task.
    """
    return next(
        m
        for m in ctx.initial_state["messages"]
        if isinstance(m, HumanMessage) and m.additional_kwargs.get("visible_to")
    )


class TestCheckpointThread:
    async def test_a_subagent_runs_on_its_own_thread_not_the_conversation_s(self, gmail_subagent):
        """The thread is where the subagent's history lives. Sharing the
        conversation's would hand it the executor's transcript, and every
        provider would see every other provider's work."""
        ctx, _, error = await prepare_subagent_execution("gmail", "read my mail", _configurable())

        assert error is None
        assert ctx is not None
        assert ctx.config["configurable"]["thread_id"] == f"gmail_{CONV_THREAD}"

    async def test_two_integrations_on_one_conversation_get_separate_threads(
        self, gmail_subagent, monkeypatch
    ):
        gmail_ctx, _, _ = await prepare_subagent_execution("gmail", "read mail", _configurable())

        monkeypatch.setattr(
            handoff_tools,
            "_resolve_subagent",
            AsyncMock(return_value=(MagicMock(), "calendar_agent", "calendar", False)),
        )
        cal_ctx, _, _ = await prepare_subagent_execution("calendar", "my day", _configurable())

        assert gmail_ctx is not None and cal_ctx is not None
        assert (
            gmail_ctx.config["configurable"]["thread_id"]
            != cal_ctx.config["configurable"]["thread_id"]
        )

    async def test_the_same_integration_resumes_the_same_thread(self, gmail_subagent):
        """Two handoffs in one conversation must continue, not restart — that is
        what lets the second one know what the first already read."""
        first, _, _ = await prepare_subagent_execution("gmail", "read mail", _configurable())
        second, _, _ = await prepare_subagent_execution("gmail", "reply to it", _configurable())

        assert first is not None and second is not None
        assert (
            first.config["configurable"]["thread_id"] == second.config["configurable"]["thread_id"]
        )

    async def test_a_different_conversation_gets_a_different_thread(self, gmail_subagent):
        one, _, _ = await prepare_subagent_execution("gmail", "read mail", _configurable())
        two, _, _ = await prepare_subagent_execution(
            "gmail", "read mail", _configurable(thread_id="other-conv")
        )

        assert one is not None and two is not None
        assert one.config["configurable"]["thread_id"] != two.config["configurable"]["thread_id"]


class TestServiceIdentity:
    async def test_the_users_gaia_name_is_replaced_with_their_service_username(
        self, gmail_subagent
    ):
        """The executor writes tasks using the user's GAIA display name. A
        provider tool cannot search for "Dhruv" — it needs the account identity
        on that service, or the search returns nothing and the subagent reports
        no results for mail that exists."""
        ctx, _, _ = await prepare_subagent_execution(
            "gmail", "find gmail messages from user: Dhruv", _configurable()
        )

        assert ctx is not None
        assert "dhruv@gmail.com" in str(_task_message(ctx).content)
        assert "Dhruv" not in str(_task_message(ctx).content)

    async def test_the_service_username_is_carried_into_state_for_the_tools(self, gmail_subagent):
        ctx, _, _ = await prepare_subagent_execution("gmail", "read my mail", _configurable())

        assert ctx is not None
        assert ctx.initial_state["integration_usernames"] == {"gmail": "dhruv@gmail.com"}

    async def test_a_task_that_never_names_the_provider_is_left_alone(self, gmail_subagent):
        """Substitution is scoped to tasks that mention the provider, so an
        unrelated mention of the user's name survives verbatim."""
        task = "ask user: Dhruv what he wants for lunch"
        ctx, _, _ = await prepare_subagent_execution("gmail", task, _configurable())

        assert ctx is not None
        assert str(_task_message(ctx).content) == task

    async def test_an_unknown_service_username_falls_back_to_a_usable_phrase(
        self, gmail_subagent, monkeypatch
    ):
        """With no provider metadata the name still must not reach the tool as a
        search term; "authenticated user" is the instruction the model can act on."""
        monkeypatch.setattr(handoff_tools, "get_provider_metadata", AsyncMock(return_value=None))

        ctx, _, _ = await prepare_subagent_execution(
            "gmail", "find gmail messages from user: Dhruv", _configurable()
        )

        assert ctx is not None
        content = str(_task_message(ctx).content)
        assert "authenticated user" in content
        assert "Dhruv" not in content

    async def test_the_sanitized_task_is_also_what_the_run_records_as_intent(self, gmail_subagent):
        """``intent`` drives retrieval and logging; leaving it unsanitized would
        put the GAIA name back into the subagent's semantic search."""
        ctx, _, _ = await prepare_subagent_execution(
            "gmail", "find gmail messages from user: Dhruv", _configurable()
        )

        assert ctx is not None
        assert ctx.initial_state["intent"] == str(_task_message(ctx).content)


class TestPreparedContext:
    async def test_the_stream_id_reaches_the_context(self, gmail_subagent):
        """Without it the subagent's frames are published nowhere and the user
        watches a silent turn."""
        ctx, _, _ = await prepare_subagent_execution(
            "gmail", "read my mail", _configurable(), stream_id="s-1"
        )

        assert ctx is not None
        assert ctx.stream_id == "s-1"

    async def test_the_integration_id_not_the_agent_name_identifies_the_provider(
        self, gmail_subagent
    ):
        """Stored instructions and provider metadata are keyed by integration id
        ("gmail"); keying them by agent_name ("gmail_agent") silently drops every
        custom instruction the user wrote."""
        ctx, _, _ = await prepare_subagent_execution("gmail", "read my mail", _configurable())

        assert ctx is not None
        assert ctx.integration_id == "gmail"
        assert ctx.agent_name == "gmail_agent"

    async def test_the_run_starts_with_an_empty_todo_list(self, gmail_subagent):
        ctx, _, _ = await prepare_subagent_execution("gmail", "read my mail", _configurable())

        assert ctx is not None
        assert ctx.initial_state["todos"] == []

    async def test_integration_metadata_comes_back_for_the_tool_cards(self, gmail_subagent):
        _, metadata, _ = await prepare_subagent_execution("gmail", "read my mail", _configurable())

        assert metadata == {"name": "Gmail"}


class TestResolutionFailure:
    async def test_an_unresolvable_subagent_returns_an_error_instead_of_raising(self, monkeypatch):
        """``handoff`` must always hand the executor a string it can act on — a
        raise here aborts the whole turn instead of letting the model retry."""
        monkeypatch.setattr(
            handoff_tools,
            "_resolve_subagent",
            AsyncMock(return_value=(None, None, "Subagent 'nope' not found", False)),
        )

        ctx, metadata, error = await prepare_subagent_execution(
            "nope", "do something", _configurable()
        )

        assert ctx is None
        assert metadata is None
        assert error is not None
        assert "nope" in error

    async def test_a_resolution_failure_with_no_message_still_reports_something(self, monkeypatch):
        """An empty error would surface to the executor as a blank tool result."""
        monkeypatch.setattr(
            handoff_tools,
            "_resolve_subagent",
            AsyncMock(return_value=(None, None, None, False)),
        )

        _, _, error = await prepare_subagent_execution("nope", "do something", _configurable())

        assert error
