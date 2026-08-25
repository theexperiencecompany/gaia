"""How the executor gets its tools: retrieval, binding, and what happens when
binding fails.

The executor is bound to fourteen tools at build time and must *retrieve* every
other one before it can call it (`build_graph.py` `initial_tool_ids`). That
retrieve → bind → call loop is the hinge the whole executor tier turns on: a
break in it means the agent cannot do anything it was not born knowing, and the
failure mode is not an exception — it is the model being handed an empty list
and trying again.

These run the REAL executor graph (see ``_harness/graph_run.executor_graph``).
The vector store is a real ``InMemoryStore`` with no index, which is not a
limitation but the point: binding by ``exact_tool_names`` must never search it,
so any test that starts depending on embeddings will fail here rather than
silently become non-deterministic.
"""

from __future__ import annotations

from typing import Any

import pytest

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


def retrieve(*names: str, id: str = "r1") -> dict[str, Any]:
    return call("retrieve_tools", {"query": " ".join(names), "exact_tool_names": list(names)}, id)


class TestExactBinding:
    async def test_a_retrieved_tool_becomes_callable_in_the_same_turn(self):
        """The whole loop. Retrieve by exact name, then call it, then answer —
        this is how the executor reaches all 91 tools from a bound set of 14."""
        async with executor_graph(
            [
                retrieve(RETRIEVABLE),
                call(RETRIEVABLE, {"query": "cats"}, id="c1"),
                "Here is what I found.",
            ]
        ) as graph:
            run = await run_graph(graph, "search the web")

        assert run.bound_tools() == [RETRIEVABLE]
        assert run.tool_names() == ["retrieve_tools", RETRIEVABLE]
        assert run.ran(RETRIEVABLE), "the retrieved tool was never actually executed"
        assert run.final_text() == "Here is what I found."

    async def test_exact_binding_never_searches_the_vector_store(self):
        """``exact_tool_names`` resolves against the in-memory registry. If it
        ever starts hitting ChromaDB, every retrieval test becomes dependent on
        Google embeddings and quietly non-deterministic — §2.6 of the plan."""
        store = RecordingStore()

        async with executor_graph(
            [retrieve(RETRIEVABLE), call(RETRIEVABLE, {"query": "cats"}), "done"], store=store
        ) as graph:
            run = await run_graph(graph, "search the web")

        assert run.bound_tools() == [RETRIEVABLE]
        assert store.searches == [], "exact binding performed a semantic search"

    async def test_the_selection_is_announced_back_to_the_model(self):
        """The model only learns what it may call from this ToolMessage.

        Asserted verbatim, not by substring: the text is the instruction the
        model acts on, and "the name appears somewhere in there" would still
        pass if the surrounding sentence stopped telling it the tools are
        callable now.
        """
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
        """``selected_tool_ids`` accumulates. If a later turn dropped the earlier
        selection, a two-step task would need to re-retrieve between every call."""
        async with executor_graph(
            [
                retrieve(RETRIEVABLE),
                call(RETRIEVABLE, {"query": "first"}, id="c1"),
                call(RETRIEVABLE, {"query": "second"}, id="c2"),
                "Both searches done.",
            ]
        ) as graph:
            run = await run_graph(graph, "search twice")

        assert run.tool_names().count(RETRIEVABLE) == 2
        assert REJECT_NODE not in run.nodes(), "the second call was treated as unbound"


class TestWhatTheModelIsActuallyHanded:
    """``selected_tool_ids`` is what retrieval decided; this is what the provider
    received as function declarations. They are different things, and only the
    second one determines whether the model can call anything.

    Nothing asserted this before: the fake model returned ``self`` from
    ``bind_tools`` and discarded the list, so deleting the whole of
    ``build_tools_to_bind`` left every retrieval test green while the executor
    silently degraded to a chatbot with no tools at all.
    """

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
        """The claim the rest of this file makes indirectly. Retrieval updating
        state is only half of it — the tool has to reach the provider before the
        model can emit a call for it."""
        async with executor_graph([retrieve(RETRIEVABLE), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert RETRIEVABLE not in run.bound[0], "bound before it was ever retrieved"
        assert RETRIEVABLE in run.model_bound_tools()

    async def test_no_tool_is_bound_twice(self):
        """Providers reject duplicate function names outright — the whole turn
        400s. Reachable: a model can retrieve a tool that is already in the
        initial set, which puts it in the bind list twice."""
        async with executor_graph([retrieve("read"), "ok"]) as graph:
            run = await run_graph(graph, "read a file")

        bound = run.model_bound_tools()

        assert len(bound) == len(set(bound)), (
            f"duplicate function declarations: {sorted(n for n in bound if bound.count(n) > 1)}"
        )

    async def test_the_binding_order_keeps_the_cacheable_prefix_stable(self):
        """The provider caches on a prefix of the request. Retrieval-selected
        tools are appended last precisely so the stable part does not shift each
        time the model retrieves something new."""
        async with executor_graph([retrieve(RETRIEVABLE), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        before, after = run.bound[0], run.model_bound_tools()

        assert after[: len(before)] == before, (
            "retrieval reordered the stable prefix instead of appending"
        )

    async def test_a_middleware_tool_is_bound_even_though_it_is_not_an_initial_id(self):
        """``spawn_subagent`` comes from the middleware stack, not
        ``initial_tool_ids`` — it is the only tool that depends on that branch,
        and every tool the rest of the suite exercises is in both."""
        async with executor_graph(["hi"]) as graph:
            run = await run_graph(graph, "hello")

        assert "spawn_subagent" in run.model_bound_tools()


class TestUnboundToolHandling:
    async def test_calling_an_unretrieved_tool_is_corrected_not_executed(self):
        """The graph must not run a tool the model never bound, and must tell it
        how to recover — naming the tool and the exact call to make."""
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
        """The correction is only useful if the model can act on it — the graph
        must route back to the agent rather than terminate."""
        async with executor_graph(
            [
                call(RETRIEVABLE, {"query": "cats"}, id="c0"),
                retrieve(RETRIEVABLE),
                call(RETRIEVABLE, {"query": "cats"}, id="c1"),
                "Found it.",
            ]
        ) as graph:
            run = await run_graph(graph, "search the web")

        assert run.ran(RETRIEVABLE)
        assert run.final_text() == "Found it."

    async def test_a_model_that_never_retrieves_hits_the_recursion_limit(self):
        """Documents a real hazard rather than a desired behaviour: nothing
        bounds the reject → agent → reject cycle, so a model that keeps calling
        an unbound tool spins until the recursion limit and the user gets the
        step-limit error instead of an answer.

        Pinning it here means a future fix (a retry cap, or corrective text on
        the retrieval side) will turn this test red and have to be considered
        deliberately. See the plan, §9 A.
        """
        async with executor_graph([call(RETRIEVABLE, {"query": "cats"}, id="loop")] * 30) as graph:
            run = await run_graph(graph, "search the web", recursion_limit=12)

        assert run.error is not None, "the unbound-tool loop terminated on its own"
        assert run.nodes().count(REJECT_NODE) > 1


class TestScopingAndNaming:
    """Two filters that decide whether a name is bindable at all."""

    async def test_a_desktop_tool_cannot_be_retrieved_into_a_web_conversation(self):
        """Desktop tools execute on the user's machine through the desktop app.
        Binding one in a web conversation gives the model a tool whose calls go
        nowhere — it waits out the timeout and reports the desktop app is closed.

        Distinct from the initial-set test: this is the only route by which a
        model could ever obtain one, so it is the only one that matters."""
        async with executor_graph([retrieve("take_screenshot"), "ok"]) as graph:
            run = await run_graph(graph, "screenshot my screen")

        assert run.bound_tools() == []
        assert "take_screenshot" not in run.model_bound_tools()

    async def test_a_dashed_tool_name_resolves_to_its_real_underscored_tool(self):
        """MCP servers commonly expose dashed names and models echo them with
        underscores (or the reverse). Without canonicalization the call is
        rejected forever, the model retries, and the unbounded reject cycle ends
        in a step-limit error instead of the tool running."""
        async with executor_graph([retrieve("web-search-tool"), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert run.bound_tools() == [RETRIEVABLE]

    async def test_a_dashed_call_of_a_bound_tool_is_routed_not_rejected(self):
        """The same rewrite on the routing side. Binding it and then rejecting
        the call is the worst of both — the model is told the tool exists and
        cannot use it."""
        async with executor_graph([call("plan-tasks", {"tasks": []}, id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "plan something")

        assert REJECT_NODE not in run.nodes()
        assert run.ran("plan_tasks")


class TestUnknownToolNames:
    async def test_an_unknown_name_binds_nothing(self):
        async with executor_graph([retrieve("no_such_tool_xyz"), "gave up"]) as graph:
            run = await run_graph(graph, "do something impossible")

        assert run.bound_tools() == []

    async def test_an_unknown_name_is_named_back_with_a_do_not_retry(self):
        """An unknown name used to come back as ``Available tools: []`` — the
        same answer a semantic search that found nothing gives, so the model had
        no signal the NAME was wrong and would retype it until it ran out of
        steps. Retrieval now names the rejected tool and points at the query
        path, which is the only thing that breaks that loop.
        """
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
        """It is the bootstrap: if it were not bound from turn 1, nothing could
        ever be retrieved and the executor would be limited to its 14 tools."""
        async with executor_graph([retrieve(RETRIEVABLE), "ok"]) as graph:
            run = await run_graph(graph, "search the web")

        assert REJECT_NODE not in run.nodes()
        assert run.bound_tools() == [RETRIEVABLE]

    async def test_calling_retrieve_tools_with_no_names_is_corrected(self):
        """A no-arg call is a model mistake. Asserting the response is merely
        non-empty is not enough — "Available tools: []" is non-empty and tells
        the model nothing, so the corrective text that retrieval actually
        produces must survive the trip back."""
        async with executor_graph([call("retrieve_tools", {}, id="r1"), "ok"]) as graph:
            run = await run_graph(graph, "find me a tool")

        assert run.bound_tools() == []
        response = " ".join(run.results_from(SELECT_NODE)).lower()
        assert "query" in response or "exact_tool_names" in response, (
            f"the correction never reached the model: {response!r}"
        )

    async def test_asking_for_a_subagent_by_name_explains_how_to_reach_it(self):
        """Subagents are not bindable tools. Retrieval knows this and returns
        guidance naming ``handoff``; if only the (empty) bind list came back the
        model would read it as "no such thing" and give up."""
        async with executor_graph([retrieve("subagent:gmail"), "ok"]) as graph:
            run = await run_graph(graph, "check my mail")

        assert run.bound_tools() == []
        response = " ".join(run.results_from(SELECT_NODE))
        assert "handoff" in response, f"no route to the subagent was offered: {response!r}"
