"""E2E tests: the HIL coalesced approval barrier, end to end on live infra.

Real PostgreSQL (the LangGraph checkpointer, so the interrupt and the node replay
are genuine), real MongoDB (approval records, user preferences), real Redis (the
background-results bucket, the resume slot, stream publish). Two subagent graphs
guard a destructive side effect with the REAL gate; the REAL ``wait_for_subagents``
barrier collects them; the REAL resolution layer applies the decisions.

What is substituted, and why — each needs infra unrelated to the barrier itself:

* ``handoff_tools._resolve_subagent`` — name → graph lookup (OAuth/provider registry).
* ``gate._integration_name_for`` — the cosmetic card label (ChromaDB tool registry).
* ``resolution.prepare_run_from_item`` / ``run_executor_background`` — the re-dispatch
  target is the full executor agent (LLM + tool registry). The resume ``Command`` is
  captured and driven into the executor graph directly, so the dispatch decision is
  still the real one; only the agent it would wake is stood in for.

Everything else is production code: the gate, policy resolution, the approval
records, checkpoint/interrupt, the barrier loop, the resume slot, the results
bucket, and exactly-once collection.

The journey is one causal chain — nothing can be approved before both subagents
park — so it is one test, in the shape of ``test_device_bridge_e2e``'s lifecycle
test rather than split into steps that would each have to re-run the setup.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command
import pytest

from app.agents.core.background.bg_results import drain_bg_subagent_results
from app.agents.core.background.executor_runner import _record_pause
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    create_session,
    increment_pending_subagents,
)
from app.agents.core.background.subagent_runner import BackgroundHandoff, run_subagent_background
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    interrupt_payload,
)
from app.agents.tools.wait_for_subagents_tool import wait_for_subagents
from app.models.hil_models import HILPreferences
from app.services.hil import resolution
from app.services.hil.gate import decide_tool_call
from app.services.hil.resume_slot import release_resume_dispatch

pytestmark = pytest.mark.e2e

GMAIL = "gmail"
SLACK = "slack"


@pytest.fixture
async def gated_user(mongo_db):
    """A real user with HIL on and both test tools explicitly gated.

    Written through ``mongo_db`` so it lands in the same database the repository
    layer is patched at — a direct accessor would seed a database the gate never
    reads. Explicit per-tool overrides decide gating without the classifier's
    LLM call.
    """
    user_oid = ObjectId()
    await mongo_db["users"].insert_one(
        {
            "_id": user_oid,
            "email": f"hil-e2e-{user_oid}@example.com",
            "hil_preferences": HILPreferences(
                mode="always_ask",
                tool_overrides={"SEND_GMAIL": True, "SEND_SLACK": True},
            ).model_dump(),
        }
    )

    yield str(user_oid)

    await mongo_db["users"].delete_one({"_id": user_oid})


def _make_subagent_graph(name: str, conv: str, side_effects: dict[str, int], saver: Any):
    """A subagent whose node runs the REAL gate around a real side effect."""
    tool_name = f"SEND_{name.upper()}"

    async def act(state: MessagesState, config: RunnableConfig) -> dict:
        call = {"id": f"tc-{name}-{conv}", "name": tool_name, "args": {"to": name}}
        request = ToolCallRequest(
            tool_call=call,
            tool=None,
            state={"messages": [AIMessage(content="", tool_calls=[call])]},
            runtime=SimpleNamespace(config=config),
        )

        async def handler(_req: Any) -> ToolMessage:
            side_effects[name] += 1
            return ToolMessage(
                content=f"{name} message delivered",
                tool_call_id=call["id"],
                name=tool_name,
            )

        # The gate decides and never executes, so the node runs the tool
        # itself — the same two lines every real adapter uses.
        blocked = await decide_tool_call(request)
        return {"messages": [blocked or await handler(request)]}

    g = StateGraph(MessagesState)
    g.add_node("act", act)
    g.add_edge(START, "act")
    g.add_edge("act", END)
    return g.compile(checkpointer=saver)


def _subagent_ctx(
    name: str, graphs: dict[str, Any], conv: str, user_id: str, stream: str
) -> SubagentExecutionContext:
    configurable = {
        "thread_id": f"{name}_executor_{conv}",
        "conversation_id": conv,
        "user_id": user_id,
        "stream_id": stream,
        "user_messages": ["send the updates"],
    }
    return SubagentExecutionContext(
        subagent_graph=graphs[name],
        agent_name=name,
        config={"configurable": configurable},
        configurable=configurable,
        integration_id=name,
        initial_state={"messages": [HumanMessage(content=f"send via {name}")]},
        user_id=user_id,
        stream_id=stream,
    )


async def _executor_node(state: MessagesState, config: RunnableConfig) -> dict:
    """The executor's node runs the REAL barrier tool."""
    return {"messages": [AIMessage(content=await wait_for_subagents.coroutine(config, 30))]}


def _build_executor_graph(saver: Any):
    eg = StateGraph(MessagesState)
    eg.add_node("join", _executor_node)
    eg.add_edge(START, "join")
    eg.add_edge("join", END)
    return eg.compile(checkpointer=saver)


@dataclass(frozen=True)
class _Journey:
    """The one run's fixed context, shared by every phase of the journey."""

    conv: str
    stream: str
    user_id: str
    graphs: dict[str, Any]
    side_effects: dict[str, int]
    executor_graph: Any
    executor_config: dict[str, Any]
    approvals: Any


async def _park_both_subagents(j: _Journey) -> dict[str, Any]:
    """Both background subagents run concurrently and PARK on the gate."""
    increment_pending_subagents(j.stream)
    increment_pending_subagents(j.stream)
    await asyncio.gather(
        run_subagent_background(
            _subagent_ctx(GMAIL, j.graphs, j.conv, j.user_id, j.stream),
            j.stream,
            handoff=BackgroundHandoff(integration_id=GMAIL),
        ),
        run_subagent_background(
            _subagent_ctx(SLACK, j.graphs, j.conv, j.user_id, j.stream),
            j.stream,
            handoff=BackgroundHandoff(integration_id=SLACK),
        ),
    )

    records = await j.approvals.find({"conversation_id": j.conv}).to_list(10)
    assert len(records) == 2, (
        "both gated subagents must file a pending approval; bucket="
        f"{await drain_bg_subagent_results(j.conv)}"
    )
    assert sorted(r.get("subagent_thread_id") or "" for r in records) == sorted(
        [f"{GMAIL}_executor_{j.conv}", f"{SLACK}_executor_{j.conv}"]
    ), "each record must carry its parked subagent's checkpoint thread"
    assert j.side_effects == {GMAIL: 0, SLACK: 0}, "nothing may run before approval"
    return {r["subagent_agent_name"]: r for r in records}


async def _pause_executor_on_batch(j: _Journey, by_agent: dict[str, Any]) -> dict:
    """The barrier pauses the executor ONCE, with the whole batch."""
    await j.executor_graph.ainvoke(
        {"messages": [HumanMessage(content="collect")]}, j.executor_config
    )
    snapshot = await j.executor_graph.aget_state(j.executor_config)
    payload = interrupt_payload(getattr(snapshot, "interrupts", ()) or ())
    assert snapshot.next, "the executor thread must be parked"
    assert sorted(payload.get("approval_ids", [])) == sorted(
        [by_agent[GMAIL]["_id"], by_agent[SLACK]["_id"]]
    ), f"one interrupt must carry both approvals, got type={payload.get('type')}"
    return payload


async def _approve_gmail_and_repark(
    j: _Journey, by_agent: dict[str, Any], captured: list[Command], run: ExecutorRun
) -> None:
    """Approve gmail: resume, collect exactly once, re-park for slack."""
    await resolution.resolve_approval(
        approval_id=by_agent[GMAIL]["_id"], user_id=j.user_id, kind="approve"
    )
    assert len(captured) == 1, "one decision dispatches exactly one resume"

    await j.executor_graph.ainvoke(captured[0], j.executor_config)
    assert j.side_effects[GMAIL] == 1, "the approved action runs exactly once"
    assert j.side_effects[SLACK] == 0, "the undecided sibling stays put"

    snapshot = await j.executor_graph.aget_state(j.executor_config)
    payload = interrupt_payload(getattr(snapshot, "interrupts", ()) or ())
    assert payload.get("approval_ids") == [by_agent[SLACK]["_id"]], (
        "the executor re-parks for the remaining approval only"
    )
    gmail_record = await j.approvals.find_one({"_id": by_agent[GMAIL]["_id"]})
    assert gmail_record.get("subagent_collected_at") is not None, (
        "a collected subagent must be stamped so the join never redoes it"
    )

    assert await _record_pause(
        run,
        "collect subagents",
        j.executor_config["configurable"],
        tuple(payload.get("approval_ids", [])),
    ), "the second round needs its own resume context"


async def _deny_slack_and_finish(
    j: _Journey, by_agent: dict[str, Any], captured: list[Command]
) -> None:
    """Deny slack: the executor finishes, the action never runs."""
    await resolution.resolve_approval(
        approval_id=by_agent[SLACK]["_id"],
        user_id=j.user_id,
        kind="deny",
        feedback="don't post this",
    )
    assert len(captured) == 2, "the second decision dispatches its own resume"

    final_state = await j.executor_graph.ainvoke(captured[1], j.executor_config)
    snapshot = await j.executor_graph.aget_state(j.executor_config)
    assert not snapshot.next, "the executor thread is finished"

    # outcome.text accumulates from streamed LLM tokens and these toy
    # graphs have no LLM, so the join's own output is asserted
    # structurally; each subagent's real content is read from its
    # checkpointed thread below.
    final_text = final_state["messages"][-1].content
    assert (
        f'<subagent_result agent="{GMAIL}">' in final_text
        and f'<subagent_result agent="{SLACK}">' in final_text
    ), f"the join returns both sections in one output, got: {final_text[:160]}"

    gmail_thread = await j.graphs[GMAIL].aget_state(
        {"configurable": {"thread_id": f"{GMAIL}_executor_{j.conv}"}}
    )
    assert "gmail message delivered" in str(gmail_thread.values["messages"][-1].content), (
        "the approved subagent's thread holds the delivered result"
    )

    slack_thread = await j.graphs[SLACK].aget_state(
        {"configurable": {"thread_id": f"{SLACK}_executor_{j.conv}"}}
    )
    slack_last = str(slack_thread.values["messages"][-1].content)
    assert "NOT performed" in slack_last and "don't post this" in slack_last, (
        f"the denied subagent is told, with the user's words: {slack_last[:120]}"
    )
    assert j.side_effects[SLACK] == 0, "a denied action never runs"
    assert j.side_effects[GMAIL] == 1, "the approved action ran exactly once overall"


class TestCoalescedApprovalBarrier:
    async def test_batch_pause_approve_deny_journey(
        self,
        gated_user: str,
        mongo_db,
        real_redis,
        hil_approvals_collection,
        postgres_url: str,
    ) -> None:
        user_id = gated_user
        conv = f"e2e-hil-{ObjectId()}"
        stream = f"e2e-stream-{ObjectId()}"
        side_effects: dict[str, int] = {GMAIL: 0, SLACK: 0}

        create_session(stream, RunKind.QUEUED)

        async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
            await saver.setup()

            graphs = {
                GMAIL: _make_subagent_graph(GMAIL, conv, side_effects, saver),
                SLACK: _make_subagent_graph(SLACK, conv, side_effects, saver),
            }
            executor_graph = _build_executor_graph(saver)
            executor_config = {
                "configurable": {
                    "thread_id": f"executor_{conv}",
                    "conversation_id": conv,
                    "user_id": user_id,
                    "stream_id": stream,
                }
            }
            journey = _Journey(
                conv=conv,
                stream=stream,
                user_id=user_id,
                graphs=graphs,
                side_effects=side_effects,
                executor_graph=executor_graph,
                executor_config=executor_config,
                approvals=hil_approvals_collection,
            )

            async def resolve_stub(agent_ref: str, _user_id: str):
                return graphs[agent_ref], agent_ref, agent_ref, False

            with (
                patch(
                    "app.services.hil.gate._integration_name_for",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "app.agents.core.subagents.handoff_tools._resolve_subagent",
                    new=AsyncMock(side_effect=resolve_stub),
                ),
            ):
                by_agent = await _park_both_subagents(journey)
                payload = await _pause_executor_on_batch(journey, by_agent)

                # The real dataclass, not a SimpleNamespace: _record_pause reads
                # the run field by field, so a hand-rolled stand-in silently
                # loses every field the run grows (bot_message_id did exactly
                # that) and the AttributeError surfaces only as "could not
                # record resume context".
                run = ExecutorRun(
                    stream_id=stream,
                    conversation_id=conv,
                    user={"user_id": user_id},
                    kind=RunKind.QUEUED,
                    task_id="task-e2e",
                    user_message_id=None,
                )
                assert await _record_pause(
                    run,
                    "collect subagents",
                    executor_config["configurable"],
                    tuple(payload.get("approval_ids", [])),
                ), "every approval in the batch needs its resume context"

                captured: list[Command] = []

                async def fake_runner(
                    run: Any, task: str, configurable: dict, resume: Command
                ) -> None:
                    captured.append(resume)
                    # The real runner's `finally` releases the slot when it finishes.
                    await release_resume_dispatch(conv)

                prepared = SimpleNamespace(run=run, task="collect subagents", configurable={})
                with (
                    patch.object(
                        resolution, "prepare_run_from_item", AsyncMock(return_value=prepared)
                    ),
                    patch.object(resolution, "run_executor_background", fake_runner),
                ):
                    await _approve_gmail_and_repark(journey, by_agent, captured, run)
                    await _deny_slack_and_finish(journey, by_agent, captured)

                assert (
                    await hil_approvals_collection.count_documents(
                        {"conversation_id": conv, "status": "pending"}
                    )
                    == 0
                ), "no approval is left pending"
                assert await drain_bg_subagent_results(conv) == [], (
                    "the join drains the results bucket completely"
                )
