"""E2E: with TASKS_ONLY on, a request becomes a tracked task whose run reports through the outbox.

Real: the compiled tasks-only comms graph and its tools, the task's creation in Mongo, the
worker's run step with the real executor graph and its lock and stream on Redis, run
delivery into a report for the outbox, and comms' read_task over the stored record.
Substituted: both tiers' model (scripted), the tool store, the memory engine, the follow-up
chips, ChromaDB embeddings, the WebSocket fan-out and the outbox's own intake (the filed
report is captured, then stored through the real repository).

Not exercised: a real LLM, the executor graph's own trace writes (the trace the follow-up reads is seeded through the real recorder), an ARQ worker (the enqueued job is read back, not run), the
outbox's judge, compose and delivery of the report, and Postgres checkpointing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId
from langgraph.store.memory import InMemoryStore
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.core.background import executor_runner as er, todo_run_delivery as trd
from app.agents.core.graph_builder import build_graph as build_graph_module
from app.agents.core.graph_manager import GraphManager
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.constants.tasks import HIDDEN_TASK_LABEL, TASKS_ONLY_COMMS_GRAPH_NAME
from app.constants.todos import GAIA_TRACKED_LABEL, WaitingOn
from app.core.websocket_manager import websocket_manager
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.todos import todo_repository
from app.memory.ingestion import RetainedMemory
from app.models.integration_models import UserIntegrationCapabilities
from app.models.memory_models import MemoryEntry
from app.models.user_models import AuthenticatedUser
from app.services.executor_trace.recorder import RunOwner, TracedCall, begin_run, record_call
from app.services.outbox.models import Initiative, ProducerKind, RunReport, SubjectKind
from app.utils.occurrence import occurrence_stamp
from app.utils.timezone import Timezone
from app.workers.tasks.tracked_todo_tasks import _execute_on_executor
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import REJECT_NODE, call, comms_graph, run_graph
from tests.e2e.test_agent_chain import StreamingScriptedModel, streaming_model

pytestmark = pytest.mark.e2e

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"
SERVICE = "app.services.tracked_todo_service"
SILENCE = "<silence>handed off</silence>"
USER = AuthenticatedUser(user_id=str(ObjectId()), email="tasks-only@test.local", name="Tasks Only")
RESULT = "Three flights to Lisbon: TAP EUR 212, Ryanair EUR 148, easyJet EUR 171."
START = {
    "title": "Lisbon flights",
    "request": "Find the cheapest flights to Lisbon next month and list three options.",
    "acceptance_criteria": ["three options are listed with prices"],
    "desired_outcome": "books the cheapest sensible flight",
    "time_horizon": "one_shot",
}


@pytest.fixture(autouse=True)
async def _owner(mongo_db: AsyncIOMotorDatabase) -> AsyncIterator[None]:
    await mongo_db["users"].update_one(
        {"_id": ObjectId(USER.user_id)},
        {"$set": {"email": USER.email, "name": USER.name, "timezone": "UTC"}},
        upsert=True,
    )
    yield
    for collection in ("todos", "conversations", "outbox_items", "executor_runs"):
        await mongo_db[collection].delete_many({"user_id": USER.user_id})


@pytest.fixture(autouse=True)
def _offline_seams(real_tool_registry: Any) -> Iterator[None]:
    """Double the todo's ChromaDB embeddings and VFS projection, off this path and never asserted on."""
    with (
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.update_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch(f"{SERVICE}.store_canvas_embedding", new_callable=AsyncMock),
        patch(f"{SERVICE}.schedule_gaia_tasks_sync"),
    ):
        yield


@dataclass
class Stack:
    comms: Any
    comms_model: StreamingScriptedModel
    executor_model: StreamingScriptedModel
    #: The jobs the task's creation put on the queue, as (task name, todo id, stamp).
    enqueued: list[tuple[str, str, int | None]] = field(default_factory=list)
    #: Every report the todo's run filed with the outbox.
    submitted: list[RunReport] = field(default_factory=list)


@asynccontextmanager
async def open_stack(*, comms: list[Any], executor: list[Any]) -> AsyncIterator[Stack]:
    """Open the real tasks-only comms and executor graphs, each tier's model scripted."""
    built = Stack(
        comms=None,
        comms_model=streaming_model(comms),
        executor_model=streaming_model(executor),
    )

    async def record_submit(report: RunReport) -> None:
        built.submitted.append(report)

    async def record_enqueue(_pool: Any, name: str, todo_id: str, *_: Any, **kwargs: Any) -> object:
        built.enqueued.append((name, todo_id, kwargs.get("scheduled_for")))
        return object()

    memory = MagicMock()
    memory.retain_single = AsyncMock(
        return_value=RetainedMemory(
            entry=MemoryEntry(id="m", content="m", category_path="general"),
            outcome="new",
        )
    )
    memory.recall = AsyncMock(return_value=MagicMock(entries=[], episodes=[]))
    memory.retain = AsyncMock()
    no_checkpointer = AsyncMock(return_value=None)

    async with AsyncExitStack() as stack:
        for patcher in (
            patch.object(
                build_graph_module, "get_tools_store", AsyncMock(return_value=InMemoryStore())
            ),
            patch.object(build_graph_module, "get_checkpointer_manager", no_checkpointer),
            patch("app.services.checkpoint_thread_reset.get_checkpointer_manager", no_checkpointer),
            patch("app.services.conversation_service.get_checkpointer_manager", no_checkpointer),
            patch(
                "app.agents.core.background.todo_run.reset_conversation_threads",
                new=AsyncMock(return_value=None),
            ),
            patch(
                f"{FOLLOW_UP_NODE}.ainvoke_structured",
                new=AsyncMock(return_value=FollowUpActions(actions=[])),
            ),
            patch(
                f"{FOLLOW_UP_NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value=UserIntegrationCapabilities(tool_names=[])),
            ),
            patch("app.agents.tools.memory_tools.memory_engine", memory),
            patch("app.agents.core.nodes.memory_node.memory_engine", memory),
            patch.object(websocket_manager, "broadcast_to_user", new=AsyncMock()),
            patch.object(trd, "submit", new=record_submit),
            patch.object(er, "submit", new=record_submit),
            patch(f"{SERVICE}.enqueue_worker_job", new=record_enqueue),
            patch(f"{SERVICE}.RedisPoolManager.get_pool", new=AsyncMock()),
        ):
            stack.enter_context(patcher)
        executor_graph = await stack.enter_async_context(
            build_graph_module.build_executor_graph(
                chat_llm=built.executor_model, in_memory_checkpointer=True
            )
        )
        built.comms = await stack.enter_async_context(
            build_graph_module.build_comms_graph(
                chat_llm=built.comms_model, in_memory_checkpointer=True, tasks_only=True
            )
        )
        graphs = {"executor_agent": executor_graph, TASKS_ONLY_COMMS_GRAPH_NAME: built.comms}
        stack.enter_context(
            patch.object(
                GraphManager,
                "get_graph",
                new=AsyncMock(side_effect=lambda name="default_graph": graphs[name]),
            )
        )
        try:
            yield built
        finally:
            await drain_background_runs()


def _executor_run(todo_id: str) -> list[Any]:
    """Script the executor to close its todo as the brief demands, then report."""
    return [
        call("retrieve_tools", {"exact_tool_names": ["complete_tracked_todo"]}, call_id="x1"),
        call(
            "complete_tracked_todo",
            {"todo_id": todo_id, "summary": "Listed three options."},
            call_id="x2",
        ),
        RESULT,
    ]


async def _the_task() -> tuple[str, Any]:
    (task,) = await todo_repository.list_active_tracked(USER.user_id, limit=5)
    return task.id, task


class TestARequestBecomesATask:
    @pytest.mark.usefixtures("mongo_db", "real_redis")
    async def test_the_request_is_a_hidden_task_armed_to_run_now(self) -> None:
        thread = f"chat-{uuid4()}"
        async with open_stack(
            comms=[call("start_task", START, call_id="c1"), SILENCE], executor=[]
        ) as stack:
            run = await run_graph(
                stack.comms, "find me flights to Lisbon", thread_id=thread, user_id=USER.user_id
            )

        assert run.ran("start_task")
        assert "task_id" in (run.result_for("start_task") or "")
        task_id, task = await _the_task()
        assert run.tool_names() == ["start_task"]
        assert {GAIA_TRACKED_LABEL, HIDDEN_TASK_LABEL} <= set(task.labels)
        assert task.waiting_on is WaitingOn.TIME
        assert task.source_conversation_id == thread
        assert task.canvas_content is not None
        assert "three options are listed with prices" in task.canvas_content
        assert START["request"] in task.canvas_content
        assert [(name, tid) for name, tid, _ in stack.enqueued] == [
            ("execute_tracked_todo", task_id)
        ]
        assert stack.enqueued[0][2] == occurrence_stamp(task.scheduled_at)

    @pytest.mark.usefixtures("mongo_db", "real_redis")
    async def test_the_executor_runs_as_the_tasks_run_and_its_result_reaches_the_outbox(
        self,
    ) -> None:
        async with open_stack(
            comms=[call("start_task", START, call_id="c1"), SILENCE], executor=[]
        ) as stack:
            await run_graph(
                stack.comms, "find me flights", thread_id=f"chat-{uuid4()}", user_id=USER.user_id
            )
            task_id, _ = await _the_task()
            stack.executor_model.responses = streaming_model(_executor_run(task_id)).responses
            doc = await todo_repository.get_by_id(task_id)
            assert doc is not None
            await _execute_on_executor(doc, user_tz=Timezone.utc(), user_data=USER)

        (filed,) = stack.submitted
        assert filed.producer is ProducerKind.TODO
        assert filed.subject.kind is SubjectKind.TODO_RUN
        assert filed.subject.series == f"todo:{task_id}"
        assert filed.initiative is Initiative.ASKED
        assert filed.guidance is not None and filed.guidance.runs_once is True
        assert RESULT in filed.result
        closed = await todo_repository.get_by_id(task_id)
        assert closed is not None and closed.completed

    @pytest.mark.usefixtures("mongo_db", "real_redis")
    async def test_a_follow_up_is_answered_from_the_tasks_record_without_running_it_again(
        self,
    ) -> None:
        async with open_stack(
            comms=[call("start_task", START, call_id="c1"), SILENCE], executor=[]
        ) as stack:
            await run_graph(
                stack.comms, "find me flights", thread_id=f"chat-{uuid4()}", user_id=USER.user_id
            )
            task_id, _ = await _the_task()
            stack.executor_model.responses = streaming_model(_executor_run(task_id)).responses
            doc = await todo_repository.get_by_id(task_id)
            assert doc is not None
            await _execute_on_executor(doc, user_tz=Timezone.utc(), user_data=USER)
            (filed,) = stack.submitted
            owner = RunOwner(USER.user_id, "task-chat", "run-1", task_id)
            await begin_run(owner)
            at = datetime.now(UTC)
            await record_call(
                owner,
                TracedCall(
                    "GMAIL_SEND_EMAIL", "tc1", {"to": "priya@example.com"}, "sent", False, at, at
                ),
            )
            await outbox_items_repository.insert_if_new(
                filed, expires_at=datetime.now(UTC) + timedelta(days=1)
            )
            stack.comms_model.responses = streaming_model(
                [call("read_task", {"task_id": task_id}, call_id="r1"), "TAP is EUR 212."]
            ).responses

            run = await run_graph(
                stack.comms,
                "what was the TAP price?",
                thread_id=f"other-{uuid4()}",
                user_id=USER.user_id,
            )
            stack.comms_model.responses = streaming_model(
                [call("read_task", {"task_id": task_id, "level": "trace"}, call_id="r2"), "ok"]
            ).responses
            traced = await run_graph(
                stack.comms,
                "what exactly did it do?",
                thread_id=f"other-{uuid4()}",
                user_id=USER.user_id,
            )

        record = run.result_for("read_task") or ""
        assert RESULT in record
        assert "observed" in record
        assert not run.ran("start_task") and not run.ran("message_task")
        assert len(stack.enqueued) == 1
        assert "GMAIL_SEND_EMAIL" in (traced.result_for("read_task") or "")


class TestTheFlagSelectsTheSurface:
    @pytest.mark.usefixtures("mongo_db", "real_redis")
    async def test_tasks_only_comms_has_no_direct_executor(self) -> None:
        async with open_stack(
            comms=[call("call_executor", {"task": "x"}, call_id="c1"), "ok"], executor=[]
        ) as stack:
            run = await run_graph(stack.comms, "do a thing", user_id=USER.user_id)

        bound = set(stack.comms_model.bound[-1])
        assert {"start_task", "message_task", "cancel_task", "find_tasks", "read_task"} <= bound
        assert not bound & {"call_executor", "cancel_executor", "read_work_record"}
        assert REJECT_NODE in run.nodes()
        assert not run.ran("call_executor")

    async def test_flag_off_comms_is_unchanged(self) -> None:
        async with comms_graph(["ok"]) as graph:
            run = await run_graph(graph, "hello")

        bound = set(run.model_bound_tools())
        assert {"call_executor", "cancel_executor", "read_work_record"} <= bound
        assert not bound & {"start_task", "message_task", "cancel_task", "find_tasks", "read_task"}
