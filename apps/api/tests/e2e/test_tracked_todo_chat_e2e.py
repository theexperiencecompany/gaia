"""E2E: a tracked todo's own hidden chat, from its run to the user opening it, on live infra.

Real: the worker's run step, the chat's get-or-create on the real unique index,
the executor lock and stream on Redis, the compiled executor and comms graphs on
the Postgres checkpointer, the executor-thread reset, delivery (saved report,
in-app notification, activity log) and the HTTP routes, all on real Mongo.
Substituted: both graphs' model (scripted), the tool store (in memory), the
memory engine and follow-up chip generator, and the WebSocket fan-out (recorded).

Not exercised: a real LLM choosing these calls, the ARQ lock/retry ladder above
the run step (unit-tested in test_tracked_todo_tasks), and an approval resume.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId
from httpx import AsyncClient
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.store.memory import InMemoryStore
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.core.background.todo_run import TodoRunFailedError
from app.agents.core.graph_builder import build_graph as build_graph_module
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.graph_manager import GraphManager
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.constants.memory import ReconcileOutcome
from app.constants.todos import GAIA_TRACKED_LABEL, TodoActivityEvent
from app.core.stream_manager import stream_manager
from app.core.websocket_manager import websocket_manager
from app.db.mongodb import indexes
from app.db.repositories.todos import todo_repository
from app.memory.ingestion import RetainedMemory
from app.models.integration_models import UserIntegrationCapabilities
from app.models.memory_models import MemoryEntry
from app.models.message_models import MessageRequestWithHistory
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.services.chat import stream as chat_stream
from app.services.conversation_service import get_or_create_todo_conversation
from app.services.tracked_todo_service import TrackedTodoService
from app.utils.timezone import Timezone
from app.workers.tasks.tracked_todo_tasks import _execute_on_executor
from tests.conftest import FAKE_USER, FAKE_USER_2
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import call
from tests.e2e._harness.transcript import Transcript
from tests.e2e.test_agent_chain import StreamingScriptedModel, streaming_model

pytestmark = pytest.mark.e2e

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"
RESET_MODULE = "app.services.checkpoint_thread_reset"
CONVERSATIONS_MODULE = "app.services.conversation_service"
TITLE = "Watch the staging deploy"
REPORT = "Deploy is green: all 3 checks passed."
SECOND_REPORT = "Still green on the second check."
NARRATED = "Your staging deploy is green."
FOLLOW_UP_REPLY = "It is still green; nothing has failed since the last run."
#: Pure and outside the executor's initial tools: reaching it runs the real
#: retrieve -> bind -> call hop, and its card is the tool's own real output.
FLOWCHART = {"description": "the deploy's three checks", "direction": "LR"}


def executor_run(report: str) -> list[Any]:
    """One executor run: find the tool, use it, report."""
    return [
        call("retrieve_tools", {"exact_tool_names": ["create_flowchart"]}, call_id="tc_find"),
        call("create_flowchart", FLOWCHART, call_id="tc_flow"),
        report,
    ]


@dataclass
class Stack:
    """The live pieces one test drives, and what they recorded."""

    checkpointer: CheckpointerManager
    executor_model: StreamingScriptedModel
    comms_model: StreamingScriptedModel
    #: Every WebSocket event a client of the user would have received, in order.
    pushed: list[dict[str, Any]] = field(default_factory=list)

    def pushed_of(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.pushed if event.get("type") == kind]

    async def threads_of(self, conversation_id: str) -> dict[str, str]:
        """Each Postgres checkpoint thread the conversation owns, by its oldest checkpoint id."""
        assert self.checkpointer.pool is not None
        async with self.checkpointer.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT thread_id, min(checkpoint_id) FROM checkpoints "
                "WHERE thread_id LIKE %s GROUP BY thread_id",
                (f"%{conversation_id}%",),
            )
            return {row[0]: row[1] for row in await cur.fetchall()}

    async def wipe_threads_of(self, conversation_id: str) -> None:
        checkpointer = self.checkpointer.get_checkpointer()
        for thread_id in await self.threads_of(conversation_id):
            await checkpointer.adelete_thread(thread_id)


@pytest.fixture
async def checkpointer(postgres_url: str) -> AsyncIterator[CheckpointerManager]:
    """Yield the app's own checkpointer manager on the real Postgres, as every graph and the reset reach it."""
    manager = await CheckpointerManager(conninfo=postgres_url, max_pool_size=4).setup()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
async def owner(mongo_db: AsyncIOMotorDatabase) -> AsyncIterator[AuthenticatedUser]:
    """Yield the HTTP client's user as a real Mongo user, with nothing of theirs left from a previous run."""
    user_id = FAKE_USER.user_id
    for collection in ("todos", "conversations", "notifications"):
        await mongo_db[collection].delete_many({"user_id": user_id})
    await mongo_db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"email": FAKE_USER.email, "name": FAKE_USER.name, "timezone": "UTC"}},
        upsert=True,
    )
    yield FAKE_USER
    for collection in ("todos", "conversations", "notifications"):
        await mongo_db[collection].delete_many({"user_id": user_id})


@pytest.fixture(autouse=True)
async def _binding_index(mongo_db: AsyncIOMotorDatabase) -> None:
    """Create the one-chat-per-todo index startup ships, from its shipped spec, on this test database.

    Dropped first: the test database outlives a run, and an index left by an older
    spec would otherwise stand in for the one under test.
    """
    collection = mongo_db["conversations"]
    for spec in await collection.list_indexes().to_list(None):
        if dict(spec["key"]) == dict(indexes.CONVERSATION_TODO_BINDING_KEYS):
            await collection.drop_index(spec["name"])
    await collection.create_index(
        indexes.CONVERSATION_TODO_BINDING_KEYS, **indexes.CONVERSATION_TODO_BINDING_OPTIONS
    )


@pytest.fixture(autouse=True)
def _offline_seams() -> Iterator[None]:
    """Double the todo's ChromaDB embeddings and VFS projection: off this path, never asserted on."""
    with (
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.update_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch("app.services.tracked_todo_service.store_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.schedule_gaia_tasks_sync"),
    ):
        yield


class FailingModel(StreamingScriptedModel):
    """A model whose provider errors on every call, the way an outage does."""

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise RuntimeError("the model provider is down")
        yield  # pragma: no cover — makes this an async generator, as the real one is

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the model provider is down")


OpenStack = Callable[..., AbstractAsyncContextManager[Stack]]


@pytest.fixture
def open_stack(
    checkpointer: CheckpointerManager,
    real_redis: Any,
    real_tool_registry: Any,
    owner: AuthenticatedUser,
) -> OpenStack:
    """Open both real graphs on the real checkpointer, each tier's model scripted by the test."""

    @asynccontextmanager
    async def opened(
        *,
        executor: Sequence[Any] | StreamingScriptedModel,
        comms: Sequence[Any] = (),
    ) -> AsyncIterator[Stack]:
        built = Stack(
            checkpointer=checkpointer,
            executor_model=executor
            if isinstance(executor, StreamingScriptedModel)
            else streaming_model(executor),
            comms_model=streaming_model(comms),
        )

        async def record_push(_user_id: str, event: dict[str, Any]) -> None:
            built.pushed.append(event)

        memory = MagicMock()
        memory.retain_single = AsyncMock(
            return_value=RetainedMemory(
                entry=MemoryEntry(id="mem-todo-chat", content="m", category_path="general"),
                outcome=ReconcileOutcome.NEW,
            )
        )
        memory.recall = AsyncMock(return_value=MagicMock(entries=[], episodes=[]))
        the_checkpointer = AsyncMock(return_value=checkpointer)

        async with AsyncExitStack() as stack:
            for patcher in (
                patch.object(
                    build_graph_module, "get_tools_store", AsyncMock(return_value=InMemoryStore())
                ),
                patch.object(build_graph_module, "get_checkpointer_manager", the_checkpointer),
                patch(f"{RESET_MODULE}.get_checkpointer_manager", the_checkpointer),
                patch(f"{CONVERSATIONS_MODULE}.get_checkpointer_manager", the_checkpointer),
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
                patch.object(websocket_manager, "broadcast_to_user", new=record_push),
            ):
                stack.enter_context(patcher)
            graphs = {
                "executor_agent": await stack.enter_async_context(
                    build_graph_module.build_executor_graph(chat_llm=built.executor_model)
                ),
                "comms_agent": await stack.enter_async_context(
                    build_graph_module.build_comms_graph(chat_llm=built.comms_model)
                ),
            }
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
                # Inside the patches: nothing a run left going may reach the real services.
                await drain_background_runs()

    return opened


async def _new_tracked_todo(owner: AuthenticatedUser, title: str = TITLE) -> str:
    created = await TrackedTodoService.create_tracked_todo(owner.user_id, title)
    return created.id


async def _run(todo_id: str, owner: AuthenticatedUser) -> None:
    """One run of the todo, through the worker's own run step."""
    doc = await todo_repository.get_by_id(todo_id)
    assert doc is not None
    await _execute_on_executor(doc, user_data=owner, user_tz=Timezone.utc())


async def _chat_of(mongo_db: AsyncIOMotorDatabase, todo_id: str) -> dict[str, Any]:
    (chat,) = await mongo_db["conversations"].find({"todo_id": todo_id}).to_list(None)
    return chat


async def _follow_up(conversation_id: str, owner: AuthenticatedUser, message: str) -> Transcript:
    """One chat turn in the conversation, through the real chat stream, read back as the client sees it."""
    stream_id = str(uuid4())
    await stream_manager.start_stream(
        stream_id=stream_id, conversation_id=conversation_id, user_id=owner.user_id
    )
    await chat_stream.run_chat_stream_background(
        stream_id=stream_id,
        body=MessageRequestWithHistory(
            message=message,
            messages=[{"role": "user", "content": message}],
            conversation_id=conversation_id,
        ),
        user=owner,
        conversation_id=conversation_id,
    )
    frames = [chunk async for chunk in stream_manager.subscribe_stream(stream_id)]
    return Transcript.from_sse("".join(frames))


def _card_tool_names(message: dict[str, Any]) -> list[str]:
    return [
        str((entry.get("data") or {}).get("tool_name", entry.get("tool_name")))
        for entry in message.get("tool_data") or []
    ]


@pytest.mark.usefixtures("mongo_db")
class TestARunLandsInTheTodosOwnChat:
    async def test_the_run_streams_into_the_chat_and_its_report_stays_there(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]) as stack:
            await _run(todo_id, owner)

        chat = await _chat_of(mongo_db, todo_id)
        conversation_id = chat["conversation_id"]
        assert chat["user_id"] == owner.user_id
        assert chat["description"] == TITLE
        # Never an unread dot or a system section: the chat is reached from its todo.
        assert chat.get("is_unread") is False
        assert not chat.get("is_system_generated")

        # The client was told where to watch, and the stream it watched closed.
        (started,) = stack.pushed_of("executor.stream_started")
        assert started["conversation_id"] == conversation_id
        frames = [c async for c in stream_manager.subscribe_stream(started["stream_id"])]
        assert any("create_flowchart" in frame for frame in frames)
        assert Transcript.from_sse("".join(frames)).is_done

        # The executor's own report and card, saved under the placeholder the stream rendered into.
        (report,) = chat["messages"]
        assert (report["type"], report["response"]) == ("bot", REPORT)
        assert report["message_id"] == started["task_id"]
        assert "create_flowchart" in _card_tool_names(report)
        (landed,) = stack.pushed_of("conversation.new_message")
        assert landed["conversation_id"] == conversation_id
        assert landed["message"]["task_id"] == started["task_id"]
        assert landed["message"]["response"] == REPORT

        # What reaches the user is comms' write-up, in the app since no chat app is linked.
        note = await mongo_db["notifications"].find_one({"user_id": owner.user_id})
        assert note is not None
        assert NARRATED in str(note)
        todo = await todo_repository.get_by_id(todo_id)
        assert todo is not None and todo.activity_content is not None
        assert f"(conversation {conversation_id[:8]})" in todo.activity_content
        assert "result sent as an in-app notification" in todo.activity_content

    async def test_every_run_reuses_the_chat_on_a_fresh_execution_thread(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(
            executor=[*executor_run(REPORT), *executor_run(SECOND_REPORT)],
            comms=[NARRATED, NARRATED],
        ) as stack:
            await _run(todo_id, owner)
            conversation_id = (await _chat_of(mongo_db, todo_id))["conversation_id"]
            first_threads = await stack.threads_of(conversation_id)
            await _run(todo_id, owner)
            second_threads = await stack.threads_of(conversation_id)

        chat = await _chat_of(mongo_db, todo_id)
        assert chat["conversation_id"] == conversation_id
        assert [m["response"] for m in chat["messages"]] == [REPORT, SECOND_REPORT]
        # The second run never read the first one's execution: its thread started over.
        executor_thread = f"executor_{conversation_id}"
        assert second_threads[executor_thread] > first_threads[executor_thread]
        # Its first prompt holds no call, result or reply of the first run; what it
        # knows of that run is the activity log the brief quotes.
        first_call_of_second_run = stack.executor_model.chat_messages_log[3]
        assert not [m for m in first_call_of_second_run if isinstance(m, AIMessage | ToolMessage)]
        # The chat's own thread (what comms said in it) is kept across runs.
        assert second_threads[conversation_id] == first_threads[conversation_id]

    async def test_a_failed_run_is_kept_in_the_chat_as_its_error_and_fails_the_attempt(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(executor=FailingModel(responses=[])):
            with pytest.raises(TodoRunFailedError):
                await _run(todo_id, owner)

        (failed,) = (await _chat_of(mongo_db, todo_id))["messages"]
        assert failed["response"] == ""
        assert failed["error"]
        # A failed run tells the user nothing yet: the worker's retry ladder owns it.
        assert await mongo_db["notifications"].count_documents({"user_id": owner.user_id}) == 0
        todo = await todo_repository.get_by_id(todo_id)
        assert todo is not None and todo.activity_content is not None
        assert f"[{TodoActivityEvent.RUN_FAILED.value}]" in todo.activity_content


@pytest.mark.usefixtures("mongo_db")
class TestTheChatIsHiddenButOpensFromItsTodo:
    async def test_never_listed_or_searched_but_opened_and_synced_from_the_todo(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        todo_id = await _new_tracked_todo(owner)
        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]):
            await _run(todo_id, owner)
        conversation_id = (await _chat_of(mongo_db, todo_id))["conversation_id"]

        listed = await client.get("/api/v1/conversations", params={"limit": 50})
        assert listed.status_code == 200
        assert conversation_id not in [c["conversation_id"] for c in listed.json()["conversations"]]
        searched = await client.get("/api/v1/search", params={"query": "green"})
        assert searched.status_code == 200
        assert conversation_id not in searched.text

        opened = await client.post(f"/api/v1/todos/{todo_id}/conversation")
        assert opened.status_code == 200
        assert opened.json() == {"conversation_id": conversation_id}

        synced = await client.post(
            "/api/v1/conversations/batch-sync",
            json={"conversations": [{"conversation_id": conversation_id}]},
        )
        (row,) = synced.json()["conversations"]
        assert row["todo_id"] == todo_id
        assert [m["response"] for m in row["messages"]] == [REPORT]

    async def test_opening_before_any_run_creates_the_one_chat_its_runs_then_use(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        first = (await client.post(f"/api/v1/todos/{todo_id}/conversation")).json()
        again = (await client.post(f"/api/v1/todos/{todo_id}/conversation")).json()
        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]):
            await _run(todo_id, owner)

        assert first == again
        chat = await _chat_of(mongo_db, todo_id)
        assert chat["conversation_id"] == first["conversation_id"]
        assert [m["response"] for m in chat["messages"]] == [REPORT]

    async def test_concurrent_first_opens_make_exactly_one_chat(
        self, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        """An Open-chat tap racing the todo's first run: the unique index lets one create win."""
        todo_id = await _new_tracked_todo(owner)

        ids = await asyncio.gather(
            *(get_or_create_todo_conversation(owner.user_id, todo_id, TITLE) for _ in range(6))
        )

        assert len(set(ids)) == 1
        assert await mongo_db["conversations"].count_documents({"todo_id": todo_id}) == 1

    async def test_only_a_tracked_todo_of_the_callers_own_has_a_chat(
        self, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase, client: AsyncClient
    ) -> None:
        plain = await todo_repository.create(
            TodoDocument(user_id=owner.user_id, title="Buy milk", labels=[])
        )
        foreign = await todo_repository.create(
            TodoDocument(
                user_id=FAKE_USER_2.user_id,
                title=TITLE,
                labels=[GAIA_TRACKED_LABEL],
                vfs_path="/workspace/gaia-tasks/theirs/canvas.md",
            )
        )
        try:
            untracked = await client.post(f"/api/v1/todos/{plain.id}/conversation")
            not_theirs = await client.post(f"/api/v1/todos/{foreign.id}/conversation")
        finally:
            await mongo_db["todos"].delete_many({"user_id": FAKE_USER_2.user_id})

        assert (untracked.status_code, untracked.json()["code"]) == (409, "todo_not_tracked")
        assert (not_theirs.status_code, not_theirs.json()["code"]) == (404, "todo_not_found")
        assert (
            await mongo_db["conversations"].count_documents(
                {"todo_id": {"$in": [plain.id, foreign.id]}}
            )
            == 0
        )


@pytest.mark.usefixtures("mongo_db")
class TestWhatTheUserSeesOutlivesTheExecutionState:
    async def test_after_every_checkpoint_is_wiped_the_history_stays_and_a_follow_up_works(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        todo_id = await _new_tracked_todo(owner)
        async with open_stack(
            executor=executor_run(REPORT), comms=[NARRATED, FOLLOW_UP_REPLY]
        ) as stack:
            await _run(todo_id, owner)
            conversation_id = (await _chat_of(mongo_db, todo_id))["conversation_id"]

            await stack.wipe_threads_of(conversation_id)
            assert await stack.threads_of(conversation_id) == {}

            synced = await client.post(
                "/api/v1/conversations/batch-sync",
                json={"conversations": [{"conversation_id": conversation_id}]},
            )
            (row,) = synced.json()["conversations"]
            assert [m["response"] for m in row["messages"]] == [REPORT]

            transcript = await _follow_up(conversation_id, owner, "is it still green?")

        assert FOLLOW_UP_REPLY in transcript.final_text()
        # The turn knew which todo "it" is: comms was shown this todo, bound to the turn.
        prompt = " ".join(str(m.content) for m in stack.comms_model.chat_messages_log[-1])
        assert "ACTIVE TODO" in prompt
        assert f"id: {todo_id}" in prompt
        saved = (await _chat_of(mongo_db, todo_id))["messages"]
        assert [(m["type"], m["response"]) for m in saved][-2:] == [
            ("user", "is it still green?"),
            ("bot", FOLLOW_UP_REPLY),
        ]


@pytest.mark.usefixtures("mongo_db")
class TestDeletingTheTodoDeletesItsChat:
    async def test_the_chat_and_its_threads_go_with_the_todo(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        todo_id = await _new_tracked_todo(owner)
        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]) as stack:
            await _run(todo_id, owner)
            conversation_id = (await _chat_of(mongo_db, todo_id))["conversation_id"]
            assert await stack.threads_of(conversation_id) != {}

            deleted = await client.delete(f"/api/v1/todos/{todo_id}")

            assert deleted.status_code == 204
            assert await mongo_db["conversations"].count_documents({"todo_id": todo_id}) == 0
            assert await stack.threads_of(conversation_id) == {}
        reopened = await client.post(f"/api/v1/todos/{todo_id}/conversation")
        assert reopened.status_code == 404
