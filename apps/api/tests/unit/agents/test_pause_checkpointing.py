"""What a pause does to the tool calls that already finished beside it.

A turn can ask for several tools at once. ``create_agent`` gives each call its own
``Send``, so they are separate tasks in one superstep, and when one of them pauses for
HIL approval the others have usually already run. Whether their results survive that
pause is not a detail: if they do not, LangGraph re-runs those tasks on resume and the
user's email is sent twice, invisibly — only the replayed ToolMessage reaches the stream.

LangGraph handles this correctly on its own. It persists the writes of every task that
COMPLETED in an interrupting step, and skips those tasks on resume. Two things we do can
throw that away, and both are exercised here:

* ``durability="exit"`` makes the run-exit save the ONLY checkpoint write there is, so
  abandoning the stream early skips it (``subagent_runner`` used to ``break``).
* LangGraph emits one ``__interrupt__`` event PER paused task, so a driver that keeps
  only the last one it sees loses every other approval's id — and an approval whose id
  never reaches ``_record_pause`` gets no ``resume_item``, which makes it permanently
  un-decidable.

Where the ``interrupt()`` is raised makes no difference — a tool's own gate and a gate
bubbled up from a subagent two frames down (``handoff``) behave identically. That was
once written down as a gap; the last class here is what proves it is not.

These run against a real compiled graph with a real checkpointer and real interrupts:
nothing here is mocked, because the thing under test IS the framework contract.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
import pytest

from app.agents.core.subagents.subagent_runner import interrupt_values, merge_approvals


class ToolRun(TypedDict):
    """The graph state these fixtures run over: an append-only log of what executed."""

    ran: Annotated[list[str], operator.add]


class ToolCallSimulator:
    """A stand-in for a turn's tool calls, with a real graph behind it.

    Give it the calls a turn makes and which of them need approval; it builds the same
    shape ``create_agent`` builds — one ``Send`` per call into a single ``tools`` node —
    and records every tool body that actually executes.

    ``ran`` is the whole point: it counts EXECUTIONS, so "did the resume repeat work the
    user already paid for" is a list comparison rather than an inference from frames.
    """

    def __init__(
        self,
        *,
        calls: list[str],
        gated: set[str] | None = None,
        durability: str = "exit",
        drain: bool = True,
        nested: bool = False,
    ) -> None:
        self.calls = calls
        self.gated = gated or set()
        self.durability = durability
        #: True raises the interrupt several frames deep inside the tool, the way
        #: ``handoff`` does when it bubbles up its subagent's gate.
        self.nested = nested
        #: False reproduces the old ``break`` — abandon the stream at the first pause.
        self.drain = drain
        self.ran: list[str] = []
        #: Every approval payload seen, in arrival order. One event per paused task.
        self.interrupts: list[dict[str, Any]] = []
        self._saver = InMemorySaver()
        self._app = self._build()
        self._thread = {"configurable": {"thread_id": "sim"}}

    def _build(self) -> Any:
        graph = StateGraph(ToolRun)

        def pause_for(name: str) -> None:
            interrupt({"type": "hil_approval", "approval_id": f"appr-{name}"})

        def bubble_up_from_a_subagent(name: str) -> None:
            """Two frames deep — ``handoff`` -> ``resume_for_gate`` -> ``interrupt``."""
            pause_for(name)

        def tools(payload: dict[str, Any]) -> ToolRun:
            name = payload["tool"]
            if name in self.gated:
                if self.nested:
                    bubble_up_from_a_subagent(name)
                else:
                    pause_for(name)
            self.ran.append(name)
            return {"ran": [name]}

        graph.add_node("tools", tools)
        graph.add_conditional_edges(
            START,
            lambda _state: [Send("tools", {"tool": name}) for name in self.calls],
            path_map=["tools"],
        )
        graph.add_edge("tools", END)
        return graph.compile(checkpointer=self._saver)

    async def _drive(self, payload: Any) -> None:
        """Consume the run the way ``execute_subagent_stream`` consumes it."""
        async for mode, chunk in self._app.astream(
            payload,
            config=self._thread,
            stream_mode=["updates"],
            durability=self.durability,
        ):
            del mode
            if isinstance(chunk, dict) and "__interrupt__" in chunk:
                self.interrupts.extend(interrupt_values(chunk["__interrupt__"]))
                if not self.drain:
                    break

    async def turn(self) -> None:
        """Run the turn until it finishes or pauses."""
        await self._drive({"ran": []})

    async def approve(self) -> None:
        """Answer an approval and let the run continue."""
        await self._drive(Command(resume={"status": "approved"}))


class TestACompletedSiblingSurvivesThePause:
    """The regression: an ungated call that already ran must not run again."""

    async def test_it_runs_once_before_the_pause_and_not_again_after(self) -> None:
        sim = ToolCallSimulator(calls=["get_weather", "send_email"], gated={"send_email"})

        await sim.turn()
        assert sim.ran == ["get_weather"], (
            f"the ungated call runs while the gated one waits, got {sim.ran}"
        )

        await sim.approve()

        assert sim.ran == ["get_weather", "send_email"], (
            f"the resume must run the approved call and NOT repeat its sibling, got {sim.ran}"
        )

    async def test_abandoning_the_stream_at_the_pause_loses_it(self) -> None:
        """Why the runner drains instead of breaking.

        This is the defect itself, pinned as a fact about the framework rather than
        about our code: under ``durability="exit"`` the run-exit save is the only
        checkpoint write, so leaving the generator early skips it and the completed
        sibling has no record of having run. If this ever starts passing, LangGraph has
        changed its persistence contract and the drain in ``subagent_runner`` can go.
        """
        sim = ToolCallSimulator(
            calls=["get_weather", "send_email"], gated={"send_email"}, drain=False
        )

        await sim.turn()
        await sim.approve()

        assert sim.ran == ["get_weather", "get_weather"], (
            "breaking out under durability='exit' is expected to lose the completed "
            f"sibling's writes and re-run it, got {sim.ran}"
        )

    @pytest.mark.parametrize("durability", ["exit", "async", "sync"])
    async def test_draining_holds_at_every_durability(self, durability: str) -> None:
        # Draining is what makes this safe, not the durability setting — so the runner
        # keeps "exit" (one checkpoint write per run instead of O(steps)) without
        # trading correctness for it.
        sim = ToolCallSimulator(
            calls=["get_weather", "send_email"], gated={"send_email"}, durability=durability
        )

        await sim.turn()
        await sim.approve()

        assert sim.ran == ["get_weather", "send_email"]

    async def test_several_completed_siblings_all_survive(self) -> None:
        # One surviving sibling could be luck in task ordering; three cannot.
        sim = ToolCallSimulator(
            calls=["get_weather", "search_web", "read_file", "send_email"],
            gated={"send_email"},
        )

        await sim.turn()
        before = sorted(sim.ran)
        await sim.approve()

        assert before == ["get_weather", "read_file", "search_web"]
        assert sorted(sim.ran) == ["get_weather", "read_file", "search_web", "send_email"], (
            f"every completed sibling must survive the pause, got {sorted(sim.ran)}"
        )


class TestEveryPausedCallIsReported:
    """One ``__interrupt__`` event per paused task — so the driver must accumulate.

    The caller stamps re-dispatch context onto every id the pause reports
    (``executor_runner._record_pause``). An approval left out of that list gets no
    ``resume_item``, and deciding it later raises ApprovalNotResumableError — the user
    presses Approve and the action can never happen.
    """

    async def test_two_gated_calls_arrive_as_two_separate_events(self) -> None:
        sim = ToolCallSimulator(
            calls=["send_email", "delete_file"], gated={"send_email", "delete_file"}
        )

        await sim.turn()

        assert len(sim.interrupts) == 2, (
            "LangGraph reports each paused task on its own event; a driver that keeps "
            f"only one loses the others, got {sim.interrupts}"
        )
        assert sorted(payload["approval_id"] for payload in sim.interrupts) == [
            "appr-delete_file",
            "appr-send_email",
        ]

    async def test_nothing_gated_runs_before_its_own_decision(self) -> None:
        # The positive control for the test above: both paused, so neither acted.
        sim = ToolCallSimulator(
            calls=["send_email", "delete_file"], gated={"send_email", "delete_file"}
        )

        await sim.turn()

        assert sim.ran == [], f"a gated call must not run before it is approved, got {sim.ran}"


class TestMergingWhatThePauseReports:
    """``merge_approvals`` is what carries every id to the caller."""

    def test_several_approvals_carry_every_id(self) -> None:
        merged = merge_approvals(
            [
                {"type": "hil_approval", "approval_id": "a", "tool_name": "send_email"},
                {"type": "hil_approval", "approval_id": "b", "tool_name": "delete_file"},
            ]
        )

        assert merged["approval_ids"] == ["a", "b"], (
            "an id missing here is an approval that can never be resumed"
        )

    def test_the_first_payload_stays_readable_as_a_single_approval(self) -> None:
        # resume_for_gate reads approval_id/tool_name off the top level; merging must
        # not move them out from under it.
        merged = merge_approvals(
            [
                {"type": "hil_approval", "approval_id": "a", "tool_name": "send_email"},
                {"type": "hil_approval", "approval_id": "b", "tool_name": "delete_file"},
            ]
        )

        assert merged["approval_id"] == "a"
        assert merged["tool_name"] == "send_email"

    def test_a_lone_approval_is_passed_through_unchanged(self) -> None:
        payload = {"type": "hil_approval", "approval_id": "a", "tool_name": "send_email"}

        assert merge_approvals([payload]) == payload

    def test_nothing_pending_is_empty(self) -> None:
        # Downstream reads {} as a malformed pause and fails the run closed, which is
        # the right answer — never "approved by default".
        assert merge_approvals([]) == {}

    def test_payloads_without_an_id_do_not_fabricate_a_batch(self) -> None:
        # A malformed payload must not silently become a one-id batch that then gets
        # resume context stamped onto a nonexistent approval.
        merged = merge_approvals([{"type": "hil_approval"}, {"type": "hil_approval"}])

        assert "approval_ids" not in merged


class TestItDoesNotMatterWhereThePauseComesFrom:
    """``handoff`` / ``spawn_subagent`` / ``wait_for_subagents`` (HIL_PAUSING_TOOLS).

    These are never gated themselves — they pause from INSIDE, bubbling up the gate of
    a subagent they are driving. That distinction mattered under an earlier design and
    was written down as a gap this could not close. It is not one: LangGraph sees a task
    that interrupted, and where in the call stack the ``interrupt()`` was raised makes no
    difference to whether its siblings' completed writes are kept.
    """

    async def test_a_sibling_survives_a_pause_raised_deep_inside_a_tool(self) -> None:
        sim = ToolCallSimulator(calls=["get_weather", "handoff"], gated={"handoff"}, nested=True)

        await sim.turn()
        assert sim.ran == ["get_weather"]

        await sim.approve()

        assert sim.ran == ["get_weather", "handoff"], (
            "a pause bubbled up from a subagent protects siblings exactly like a pause "
            f"at the tool's own gate, got {sim.ran}"
        )

    async def test_and_is_lost_the_same_way_without_the_drain(self) -> None:
        # The control: same shape, same failure mode. If these two ever diverge, the
        # nested case needs its own handling after all.
        sim = ToolCallSimulator(
            calls=["get_weather", "handoff"], gated={"handoff"}, nested=True, drain=False
        )

        await sim.turn()
        await sim.approve()

        assert sim.ran == ["get_weather", "get_weather"]
