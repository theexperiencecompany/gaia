"""How the executor gets its tools: retrieval, binding, and what happens when binding fails.

The executor is bound to fourteen tools at build time (build_graph.py, initial_tool_ids) and must
retrieve every other one before it can call it. That retrieve-bind-call loop is the hinge the
whole executor tier turns on: a break in it means the agent cannot do anything it was not born
knowing, and the failure mode is not an exception, it is the model being handed an empty list and
trying again.

These run the REAL executor graph (see _harness/graph_run.executor_graph). The vector store is a
real InMemoryStore with no index, which is the point rather than a limitation: binding by
exact_tool_names must never search it, so a test that starts depending on embeddings fails here
instead of silently becoming non-deterministic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.llm import LOOP_GUARD_STOP_REPEAT
from tests.e2e._harness.graph_run import (
    REJECT_NODE,
    SELECT_NODE,
    TOOLS_NODE,
    RecordingStore,
    call,
    executor_graph,
    run_graph,
)

pytestmark = pytest.mark.e2e

#: A real registry tool that is NOT in the executor's initial_tool_ids, so it
#: can only become callable by being retrieved.
RETRIEVABLE = "web_search_tool"


def retrieve(*names: str, retrieve_id: str = "r1") -> dict[str, Any]:
    return call(
        "retrieve_tools", {"query": " ".join(names), "exact_tool_names": list(names)}, retrieve_id
    )


class TestExactBinding:
    async def test_a_retrieved_tool_becomes_callable_in_the_same_turn(self):
        """Exercises the full loop: retrieve, call, then answer — reaching all 91 tools from a bound set of 14."""
        async with executor_graph(
            [
                retrieve(RETRIEVABLE),
                call(RETRIEVABLE, {"query": "cats"}, call_id="c1"),
                "Here is what I found.",
            ]
        ) as graph:
            run = await run_graph(graph, "search the web")

        assert run.bound_tools() == [RETRIEVABLE]
        assert run.tool_names() == ["retrieve_tools", RETRIEVABLE]
        assert run.ran(RETRIEVABLE), "the retrieved tool was never actually executed"
        assert run.final_text() == "Here is what I found."

    async def test_exact_binding_never_searches_the_vector_store(self):
        """Binding by exact_tool_names must never hit ChromaDB, or every retrieval test becomes dependent on embeddings (plan §2.6)."""
        store = RecordingStore()

        async with executor_graph(
            [retrieve(RETRIEVABLE), call(RETRIEVABLE, {"query": "cats"}), "done"], store=store
        ) as graph:
            run = await run_graph(graph, "search the web")

        assert run.bound_tools() == [RETRIEVABLE]
        assert store.searches == [], "exact binding performed a semantic search"

    async def test_the_selection_is_announced_back_to_the_model(self):
        """Asserts the ToolMessage verbatim, not by substring, since a partial match would still pass if the callable-now instruction were dropped."""
        async with executor_graph([retrieve(RETRIEVABLE), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert run.results_from(SELECT_NODE) == [
            f"Bound 1 tools, call them directly:\n  - {RETRIEVABLE}"
        ]

    async def test_several_tools_bind_in_one_retrieval(self):
        async with executor_graph([retrieve(RETRIEVABLE, "get_weather"), "ok"]) as graph:
            run = await run_graph(graph, "search and check weather")

        assert sorted(run.bound_tools()) == sorted([RETRIEVABLE, "get_weather"])

    async def test_a_tool_stays_bound_for_the_rest_of_the_run(self):
        """selected_tool_ids accumulates, so a later turn doesn't need to re-retrieve between calls in the same run."""
        async with executor_graph(
            [
                retrieve(RETRIEVABLE),
                call(RETRIEVABLE, {"query": "first"}, call_id="c1"),
                call(RETRIEVABLE, {"query": "second"}, call_id="c2"),
                "Both searches done.",
            ]
        ) as graph:
            run = await run_graph(graph, "search twice")

        assert run.tool_names().count(RETRIEVABLE) == 2
        assert REJECT_NODE not in run.nodes(), "the second call was treated as unbound"


class TestWhatTheModelIsActuallyHanded:
    """Asserts what the provider actually received, not what retrieval decided — deleting build_tools_to_bind once left every retrieval test green while the executor silently lost every tool."""

    async def test_the_model_is_bound_its_starting_toolset(self):
        async with executor_graph(["hi"]) as graph:
            run = await run_graph(graph, "hello")

        bound = run.model_bound_tools()

        assert bound, "the model was handed no tools at all"
        assert "handoff" in bound and "plan_tasks" in bound

    async def test_retrieve_tools_is_bound_or_nothing_could_ever_be_retrieved(self):
        async with executor_graph(["hi"]) as graph:
            run = await run_graph(graph, "hello")

        assert "retrieve_tools" in run.model_bound_tools()

    async def test_a_retrieved_tool_is_bound_on_the_next_model_call(self):
        """Retrieval updating state is only half of it — the tool has to reach the provider before the model can emit a call for it."""
        async with executor_graph([retrieve(RETRIEVABLE), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert RETRIEVABLE not in run.bound[0], "bound before it was ever retrieved"
        assert RETRIEVABLE in run.model_bound_tools()

    async def test_no_tool_is_bound_twice(self):
        """Providers reject duplicate function names outright, so a tool already in the initial set must not be bound twice after retrieval."""
        async with executor_graph([retrieve("read"), "ok"]) as graph:
            run = await run_graph(graph, "read a file")

        bound = run.model_bound_tools()

        assert len(bound) == len(set(bound)), (
            f"duplicate function declarations: {sorted(n for n in bound if bound.count(n) > 1)}"
        )

    async def test_the_binding_order_keeps_the_cacheable_prefix_stable(self):
        """Retrieval-selected tools are appended last so the cacheable prefix never shifts when the model retrieves something new."""
        async with executor_graph([retrieve(RETRIEVABLE), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        before, after = run.bound[0], run.model_bound_tools()

        assert after[: len(before)] == before, (
            "retrieval reordered the stable prefix instead of appending"
        )

    async def test_a_middleware_tool_is_bound_even_though_it_is_not_an_initial_id(self):
        """spawn_subagent comes from the middleware stack, not initial_tool_ids — the one tool depending on that branch."""
        async with executor_graph(["hi"]) as graph:
            run = await run_graph(graph, "hello")

        assert "spawn_subagent" in run.model_bound_tools()


class TestUnboundToolHandling:
    async def test_calling_an_unretrieved_tool_is_corrected_not_executed(self):
        """The correction must name the tool and the exact call to make so the model can recover."""
        async with executor_graph(
            [call(RETRIEVABLE, {"query": "cats"}), "I will retrieve it first."]
        ) as graph:
            run = await run_graph(graph, "search the web")

        assert REJECT_NODE in run.nodes()
        assert TOOLS_NODE not in run.nodes(), "an unbound tool body executed"
        assert not run.ran(RETRIEVABLE)

        correction = run.results_from(REJECT_NODE)[0]
        assert RETRIEVABLE in correction
        assert "retrieve_tools" in correction

    async def test_the_run_recovers_after_a_correction(self):
        """The graph must route back to the agent after a correction rather than terminate."""
        async with executor_graph(
            [
                call(RETRIEVABLE, {"query": "cats"}, call_id="c0"),
                retrieve(RETRIEVABLE),
                call(RETRIEVABLE, {"query": "cats"}, call_id="c1"),
                "Found it.",
            ]
        ) as graph:
            run = await run_graph(graph, "search the web")

        assert run.ran(RETRIEVABLE)
        assert run.final_text() == "Found it."

    async def test_a_model_that_never_retrieves_hits_the_recursion_limit(self):
        """Documents a real hazard, not desired behavior: nothing bounds the reject-agent-reject cycle, so this pins the recursion-limit outcome per the plan, §9 A."""
        async with executor_graph(
            [call(RETRIEVABLE, {"query": "cats"}, call_id="loop")] * 30
        ) as graph:
            run = await run_graph(graph, "search the web", recursion_limit=12)

        assert run.error is not None, "the unbound-tool loop terminated on its own"
        assert run.nodes().count(REJECT_NODE) > 1


class TestScopingAndNaming:
    """Two filters that decide whether a name is bindable at all."""

    async def test_a_desktop_tool_cannot_be_retrieved_into_a_web_conversation(self):
        """Binding a desktop tool into a web conversation makes calls go nowhere until the model times out and reports the desktop app is closed."""
        async with executor_graph([retrieve("take_screenshot"), "ok"]) as graph:
            run = await run_graph(graph, "screenshot my screen")

        assert run.bound_tools() == []
        assert "take_screenshot" not in run.model_bound_tools()

    async def test_a_dashed_tool_name_resolves_to_its_real_underscored_tool(self):
        """Models echo dashed MCP names with underscores (or the reverse); without canonicalization the call is rejected forever."""
        async with executor_graph([retrieve("web-search-tool"), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert run.bound_tools() == [RETRIEVABLE]

    async def test_a_dashed_call_of_a_bound_tool_is_routed_not_rejected(self):
        """Same dash/underscore rewrite on the routing side — telling the model the tool exists yet rejecting the call would be the worst of both."""
        async with executor_graph([call("plan-tasks", {"tasks": []}, call_id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "plan something")

        assert REJECT_NODE not in run.nodes()
        assert run.ran("plan_tasks")


class TestUnknownToolNames:
    async def test_an_unknown_name_binds_nothing(self):
        async with executor_graph([retrieve("no_such_tool_xyz"), "gave up"]) as graph:
            run = await run_graph(graph, "do something impossible")

        assert run.bound_tools() == []

    async def test_an_unknown_name_is_named_back_with_a_do_not_retry(self):
        """An unknown name used to come back as an empty tool list indistinguishable from a failed search, so the model retried until it ran out of steps."""
        async with executor_graph([retrieve("no_such_tool_xyz"), "gave up"]) as graph:
            run = await run_graph(graph, "do something impossible")

        assert run.results_from(SELECT_NODE) == [
            (
                "Not found, nothing bound: no_such_tool_xyz. Do not retry these names; "
                "run retrieve_tools(query=...) to find what actually exists."
            )
        ]

    async def test_a_valid_name_alongside_an_unknown_one_still_binds(self):
        """One bad name must not poison the batch."""
        async with executor_graph([retrieve(RETRIEVABLE, "no_such_tool_xyz"), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert run.bound_tools() == [RETRIEVABLE]


class TestRetrievalContract:
    async def test_retrieve_tools_is_available_without_being_retrieved(self):
        """The bootstrap tool: unbound from turn 1, nothing could ever be retrieved and the executor would be limited to its 14 tools."""
        async with executor_graph([retrieve(RETRIEVABLE), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert REJECT_NODE not in run.nodes()
        assert run.bound_tools() == [RETRIEVABLE]

    async def test_calling_retrieve_tools_with_no_names_is_corrected(self):
        """A non-empty response like "Available tools: []" isn't enough — the corrective text naming query/exact_tool_names must survive the round trip."""
        async with executor_graph([call("retrieve_tools", {}, call_id="r1"), "ok"]) as graph:
            run = await run_graph(graph, "find me a tool")

        assert run.bound_tools() == []
        response = " ".join(run.results_from(SELECT_NODE)).lower()
        assert "query" in response or "exact_tool_names" in response, (
            f"the correction never reached the model: {response!r}"
        )

    async def test_binding_a_subagent_name_is_rejected_and_sends_the_model_back_to_discovery(self):
        """A subagent: entry is never bindable; echoing it back as bound would loop the model bind->reject."""
        async with executor_graph([retrieve("subagent:gmail"), "ok"]) as graph:
            run = await run_graph(graph, "check my mail")

        assert run.bound_tools() == []
        assert run.results_from(SELECT_NODE) == [
            (
                "Not found, nothing bound: subagent:gmail. Do not retry these names; "
                "run retrieve_tools(query=...) to find what actually exists."
            )
        ]


#: A Google Calendar catalog slug. Its integration is reported unconnected below.
CALENDAR_TOOL = "GOOGLECALENDAR_EVENTS_LIST"


@pytest.fixture
def calendar_not_connected() -> Iterator[None]:
    """Report Google Calendar as unconnected through the connection-status seam."""
    with patch(
        "app.services.oauth.oauth_service.get_all_integrations_status",
        AsyncMock(return_value={"googlecalendar": False}),
    ):
        yield


@pytest.mark.usefixtures("calendar_not_connected")
class TestUnconnectedIntegrationLoop:
    """The live loop: 21 retrieve_tools calls for an unconnected Google Calendar, to the recursion limit."""

    @pytest.mark.regression
    async def test_an_interactive_run_is_told_it_needs_connecting_and_what_to_do(self):
        async with executor_graph([retrieve(CALENDAR_TOOL), "ok"]) as graph:
            run = await run_graph(
                graph, "what's on my calendar today", execution_mode="interactive"
            )

        (reply,) = run.results_from(SELECT_NODE)
        assert run.bound_tools() == []
        assert reply.startswith("Google Calendar needs to be connected")
        assert 'activate_integration(integration_id="googlecalendar")' in reply
        assert "retrieve_tools(query=" not in reply
        assert f"## {CALENDAR_TOOL}" not in reply

    @pytest.mark.regression
    async def test_a_background_run_repeating_the_call_is_stopped_by_the_loop_guard(self):
        calls = [
            retrieve(CALENDAR_TOOL, retrieve_id=f"r{i}") for i in range(LOOP_GUARD_STOP_REPEAT)
        ]
        async with executor_graph([*calls, "reported it"]) as graph:
            run = await run_graph(graph, "daily agenda", execution_mode="background")

        replies = run.results_from(SELECT_NODE)
        assert len(replies) == LOOP_GUARD_STOP_REPEAT
        assert "carry on with the rest of the task" in replies[0]
        assert "activate_integration" not in replies[0]
        assert replies[-1].startswith("[Loop guard] Blocked without executing: `retrieve_tools`")
        assert run.error is None
        assert run.final_text() == "reported it"
