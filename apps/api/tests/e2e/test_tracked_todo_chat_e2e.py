"""E2E: a tracked todo's own hidden chat, from its run to the user opening it, on live infra.

Real: the worker's run step and task, the chat's get-or-create on the real unique
index, the executor lock and stream on Redis, the compiled graphs on the Postgres
checkpointer, the HIL ledger and its decision route, delivery and the HTTP routes,
all on real Mongo. Substituted: both graphs' model (scripted), the tool store, the
memory engine, the follow-up chip generator and the WebSocket fan-out (recorded).

Not exercised: a real LLM, an ARQ worker picking jobs up (they are read off the
real queue and run by the test), and the retry ladder (test_tracked_todo_tasks).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from arq.connections import ArqRedis
from bson import ObjectId
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.store.memory import InMemoryStore
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import PrivateAttr
import pytest

from app.agents.core.background.todo_run import TodoRunFailedError
from app.agents.core.graph_builder import build_graph as build_graph_module
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.graph_manager import GraphManager
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.memory import ReconcileOutcome
from app.constants.todos import (
    GAIA_TRACKED_LABEL,
    TODO_CONVERSATION_MAX_MESSAGES,
    TodoActivityEvent,
)
from app.core.stream_manager import stream_manager
from app.core.websocket_manager import websocket_manager
from app.db.mongodb import indexes
from app.db.repositories.todos import todo_repository
from app.memory.ingestion import RetainedMemory
from app.models.chat_models import ConversationModel
from app.models.hil_models import HILPreferences
from app.models.integration_models import UserIntegrationCapabilities
from app.models.memory_models import MemoryEntry
from app.models.message_models import MessageRequestWithHistory
from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.user_models import AuthenticatedUser
from app.services.chat import stream as chat_stream
from app.services.conversation_service import (
    create_conversation_service,
    get_or_create_todo_conversation,
)
from app.services.tracked_todo_service import TrackedTodoService
from app.utils.occurrence import occurrence_stamp
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from app.workers.tasks.tracked_todo_tasks import (
    _execute_on_executor,
    execute_tracked_todo,
    resume_tracked_todo,
)
from tests.conftest import FAKE_USER, FAKE_USER_2
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import call
from tests.e2e._harness.transcript import Transcript
from tests.e2e.test_agent_chain import StreamingScriptedModel, streaming_model
from tests.helpers import worker_redis_url

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
OWNED_COLLECTIONS = ("todos", "conversations", "notifications", "approval_ledger")


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
    for collection in OWNED_COLLECTIONS:
        await mongo_db[collection].delete_many({"user_id": user_id})
    await mongo_db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {"email": FAKE_USER.email, "name": FAKE_USER.name, "timezone": "UTC"},
            "$unset": {"hil_preferences": ""},
        },
        upsert=True,
    )
    yield FAKE_USER
    for collection in OWNED_COLLECTIONS:
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
        memory.retain = AsyncMock()
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
class TestAFollowUpKnowsTheRunsAboveIt:
    @pytest.mark.parametrize("notify_on_run", [True, False], ids=["told", "not-told"])
    async def test_a_follow_up_is_shown_the_report_the_chat_shows(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        notify_on_run: bool,
    ) -> None:
        """Regression: a run the user was not told of left its report only in the chat's history, so asking about it got an answer that never saw it."""
        todo_id = (
            await TrackedTodoService.create_tracked_todo(
                owner.user_id, TITLE, notify_on_run=notify_on_run
            )
        ).id
        comms = [NARRATED, FOLLOW_UP_REPLY] if notify_on_run else [FOLLOW_UP_REPLY]

        async with open_stack(executor=executor_run(REPORT), comms=comms) as stack:
            await _run(todo_id, owner)
            conversation_id = (await _chat_of(mongo_db, todo_id))["conversation_id"]
            await _follow_up(conversation_id, owner, "what did the second check find?")

        prompt = " ".join(str(m.content) for m in stack.comms_model.chat_messages_log[-1])
        assert REPORT in prompt

    async def test_a_follow_up_is_shown_the_failure_the_chat_shows(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(executor=FailingModel(responses=[])):
            with pytest.raises(TodoRunFailedError):
                await _run(todo_id, owner)
        chat = await _chat_of(mongo_db, todo_id)
        (failed,) = chat["messages"]
        async with open_stack(executor=[], comms=[FOLLOW_UP_REPLY]) as stack:
            await _follow_up(chat["conversation_id"], owner, "why did it fail?")

        prompt = " ".join(str(m.content) for m in stack.comms_model.chat_messages_log[-1])
        assert failed["error"] in prompt


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
        # The chat is never in the listed set a client diffs, so its sync is what tells it.
        synced = await client.post(
            "/api/v1/conversations/batch-sync",
            json={"conversations": [{"conversation_id": conversation_id}]},
        )
        assert synced.json() == {"conversations": [], "missing": [conversation_id]}


# ---------------------------------------------------------------------------
# Edge cases: approvals, a busy chat, the message cap, renames, deletes, other users
# ---------------------------------------------------------------------------

#: Stands in for the approval id in a scripted redeem: the model reads the real one off its prompt.
READ_APPROVAL_ID = "<the approval id in the prompt>"
APPROVAL_READY = re.compile(r"APPROVAL_READY (\S+):")
WAITING = "Waiting on your approval to draw the deploy's flowchart."
DRAWN = "Drew the deploy's flowchart."
RESUMED = "The flowchart is in; nothing else is left this run."
#: A resume does no tool work of its own, so the completion nudge asks once more.
NOTHING_PENDING = "Confirmed: the approved flowchart already ran; nothing is pending."
SKIPPED = "Skipped the flowchart, as you declined it."
RECHECK = "recheck the deploy right now"
RECHECKED = "Rechecked: the deploy is still green."
RENAMED = "Watch the production deploy"


@dataclass
class Hold:
    """Model calls held open: reached once one is waiting, and let go together on release."""

    reached: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)


class PromptReadingModel(StreamingScriptedModel):
    """A scripted model that reads its prompt as a real one does: for an approval id, and to wait.

    A redeem scripted with READ_APPROVAL_ID carries the id the ticket names; a
    call whose prompt holds a held phrase waits for the test, the way a slow
    model call keeps a run, and the chat's executor lock, held.
    """

    _holds: dict[str, Hold] = PrivateAttr(default_factory=dict)

    def hold_calls_seeing(self, phrase: str) -> Hold:
        self._holds[phrase] = Hold()
        return self._holds[phrase]

    async def _astream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        prompt = _prompt_text(messages)
        for phrase, hold in self._holds.items():
            if phrase in prompt:
                hold.reached.set()
                await hold.released.wait()
        async for chunk in super()._astream(messages, *args, **kwargs):
            yield chunk

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        result = super()._generate(messages, *args, **kwargs)
        for tool_call in result.generations[0].message.tool_calls:
            data = tool_call["args"].get("data")
            if isinstance(data, dict) and data.get("id") == READ_APPROVAL_ID:
                ticket = APPROVAL_READY.search(_prompt_text(messages))
                assert ticket, "a redeem was scripted, but no APPROVAL_READY reached the model"
                data["id"] = ticket.group(1)
        return result


def _prompt_text(messages: list[BaseMessage]) -> str:
    return " ".join(str(m.content) for m in messages)


def prompt_reading(script: Sequence[Any]) -> PromptReadingModel:
    return PromptReadingModel(responses=streaming_model(script).responses)


def gated_run(after_the_verdict: Sequence[Any]) -> PromptReadingModel:
    """Script a run that proposes the gated flowchart and says it waits, then what follows the verdict."""
    return prompt_reading(
        [
            call("retrieve_tools", {"exact_tool_names": ["create_flowchart"]}, call_id="tc_find"),
            call("create_flowchart", FLOWCHART, call_id="tc_flow"),
            WAITING,
            *after_the_verdict,
        ]
    )


def redeem() -> Any:
    return call(
        "execute",
        {
            "task_description": "draw the approved flowchart",
            "tool_name": "approve",
            "data": {"id": READ_APPROVAL_ID},
        },
        call_id="tc_redeem",
    )


@pytest.fixture
async def worker_pool(redis_url: str) -> AsyncIterator[ArqRedis]:
    """Install a real ArqRedis on the test's Redis as the worker pool, as enqueue and the run lock reach it."""
    pool = ArqRedis.from_url(worker_redis_url(redis_url))
    with patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=pool)):
        yield pool
    await pool.aclose()


async def _ask_before(mongo_db: AsyncIOMotorDatabase, tool_name: str) -> None:
    """Set the owner to be asked before every call of the tool, as their HIL settings would."""
    await mongo_db["users"].update_one(
        {"_id": ObjectId(FAKE_USER.user_id)},
        {
            "$set": {
                "hil_preferences": HILPreferences(
                    mode="always_ask", tool_overrides={tool_name: True}
                ).model_dump()
            }
        },
    )


async def _only_approval(mongo_db: AsyncIOMotorDatabase) -> dict[str, Any]:
    (row,) = await mongo_db["approval_ledger"].find({"user_id": FAKE_USER.user_id}).to_list(None)
    return row


async def _activity(todo_id: str) -> str:
    todo = await todo_repository.get_by_id(todo_id)
    assert todo is not None and todo.activity_content is not None
    return todo.activity_content


async def _queued_resumes(pool: ArqRedis) -> list[tuple[Any, ...]]:
    return [tuple(j.args) for j in await pool.queued_jobs() if j.function == "resume_tracked_todo"]


def _paid() -> AbstractContextManager[AsyncMock]:
    """Let the worker's paid-only gate pass: the plan read is off this path."""
    return patch("app.workers.tasks.tracked_todo_tasks.is_paid", AsyncMock(return_value=True))


@contextmanager
def _signed_in_as(test_app: FastAPI, user: AuthenticatedUser) -> Iterator[None]:
    original = test_app.dependency_overrides[get_current_user]
    test_app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        test_app.dependency_overrides[get_current_user] = original


@pytest.mark.usefixtures("mongo_db")
class TestAnApprovalTheRunWaitsOnStaysInTheTodosChat:
    async def test_approving_runs_the_call_and_continues_the_run_in_its_chat_and_thread(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
        worker_pool: ArqRedis,
    ) -> None:
        """The ticket run is still going when the resume job lands, as with a real model: the resume waits its turn."""
        await _ask_before(mongo_db, "create_flowchart")
        todo_id = await _new_tracked_todo(owner)
        executor = gated_run([redeem(), DRAWN, RESUMED, NOTHING_PENDING])

        async with open_stack(executor=executor, comms=[NARRATED] * 3) as stack:
            await _run(todo_id, owner)
            conversation_id = (await _chat_of(mongo_db, todo_id))["conversation_id"]
            row = await _only_approval(mongo_db)
            parked = (await client.get(f"/api/v1/todos/{todo_id}")).json()["pending_approval"]
            parked_threads = await stack.threads_of(conversation_id)

            ticket_run = executor.hold_calls_seeing("APPROVAL_READY")
            decided = await client.post(
                f"/api/v1/approvals/{row['approval_id']}/decision", json={"decision": "approve"}
            )
            await ticket_run.reached.wait()
            (enqueued,) = await _queued_resumes(worker_pool)
            landed_mid_ticket_run = await resume_tracked_todo({}, *enqueued)
            ticket_run.released.set()
            await drain_background_runs()
            (deferred,) = [job for job in await _queued_resumes(worker_pool) if job != enqueued]
            resumed = await resume_tracked_todo({}, *deferred)
            resumed_threads = await stack.threads_of(conversation_id)
            after = (await client.get(f"/api/v1/todos/{todo_id}")).json()["pending_approval"]

        # The approval belongs to the todo's chat, and the todo links to it there.
        assert (row["conversation_id"], row["owner_run_type"], row["owner_id"]) == (
            conversation_id,
            "todo",
            todo_id,
        )
        assert parked == {"approval_id": row["approval_id"], "conversation_id": conversation_id}
        assert decided.json() == {"success": True, "reason": None, "status": "approved"}

        # The approved call ran once, redeemed in the chat by the run the approval started.
        ledger = await mongo_db["approval_ledger"].find_one({"approval_id": row["approval_id"]})
        assert ledger is not None and ledger["state"] == "executed"
        # The resume that landed while that run held the chat waited instead of failing.
        assert landed_mid_ticket_run == f"resume_deferred:{todo_id} (executor busy)"
        assert deferred == (todo_id, conversation_id, row["approval_id"], row["summary"], 1)
        assert resumed == f"resumed:{todo_id}"
        assert after is None

        chat = await _chat_of(mongo_db, todo_id)
        assert [m["response"] for m in chat["messages"]] == [
            WAITING,
            NARRATED,
            # Two model messages, so two bubbles (HeldReplies, app/agents/core/held_replies.py).
            f"{RESUMED}{NEW_MESSAGE_BREAKER}{NOTHING_PENDING}",
        ]
        assert "approve" in _card_tool_names(chat["messages"][1])
        # Every leg continued the parked execution: no reset dropped its thread.
        executor_thread = f"executor_{conversation_id}"
        assert resumed_threads[executor_thread] == parked_threads[executor_thread]

        activity = await _activity(todo_id)
        assert activity.count(f"[{TodoActivityEvent.APPROVAL_GRANTED.value}]") == 1
        assert f"[{TodoActivityEvent.RUN_FAILED.value}]" not in activity
        assert activity.count(f"[{TodoActivityEvent.RUN_FINISHED.value}]") == 2

    async def test_denying_reports_the_skip_in_the_chat_and_resumes_nothing(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
        worker_pool: ArqRedis,
    ) -> None:
        await _ask_before(mongo_db, "create_flowchart")
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(executor=gated_run([SKIPPED]), comms=[NARRATED] * 2):
            await _run(todo_id, owner)
            row = await _only_approval(mongo_db)
            decided = await client.post(
                f"/api/v1/approvals/{row['approval_id']}/decision",
                json={"decision": "deny", "feedback": "not this week"},
            )
            await drain_background_runs()

        assert decided.json()["status"] == "denied"
        ledger = await mongo_db["approval_ledger"].find_one({"approval_id": row["approval_id"]})
        assert ledger is not None and ledger["state"] == "denied"
        assert await worker_pool.queued_jobs() == []
        # The run the verdict started told the chat what was skipped.
        chat = await _chat_of(mongo_db, todo_id)
        assert [m["response"] for m in chat["messages"]] == [WAITING, NARRATED]
        assert (
            f"[{TodoActivityEvent.APPROVAL_DENIED.value}] {row['approval_id']} ('not this week'): "
            f"skipped {row['summary']}"
        ) in await _activity(todo_id)


@pytest.mark.usefixtures("mongo_db")
class TestARunThatFindsItsChatBusyWaits:
    async def test_a_scheduled_run_during_a_follow_up_is_skipped_not_failed(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
        worker_pool: ArqRedis,
        real_redis: Any,
    ) -> None:
        """Regression: the scheduled run counted the user's own follow-up as a failed attempt and retried an hour later."""
        due = datetime.now(UTC)
        todo_id = (
            await TrackedTodoService.create_tracked_todo(
                owner.user_id, TITLE, schedule=TodoUpdate(scheduled_at=due)
            )
        ).id
        conversation_id = (await client.post(f"/api/v1/todos/{todo_id}/conversation")).json()[
            "conversation_id"
        ]
        # Twice: the recheck does no tool work, so the completion nudge asks once more.
        executor = prompt_reading([RECHECKED, RECHECKED])
        comms = [call("call_executor", {"task": RECHECK}, call_id="tc_exec"), "On it.", NARRATED]

        async with open_stack(executor=executor, comms=comms):
            follow_up = executor.hold_calls_seeing(RECHECK)
            following_up = asyncio.create_task(
                _follow_up(conversation_id, owner, "is it still green?")
            )
            await follow_up.reached.wait()
            assert await real_redis.exists(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
            with _paid():
                result = await execute_tracked_todo(
                    {}, todo_id, scheduled_for=occurrence_stamp(due)
                )
            follow_up.released.set()
            await following_up
            await drain_background_runs()

        assert result == f"skipped:{todo_id} (lock held)"
        todo = await todo_repository.get_by_id(todo_id)
        # Still due, so the safety net's next scan runs it; no attempt was spent.
        assert todo is not None and todo.gaia_retry_count == 0
        assert todo.scheduled_at is not None and todo.scheduled_at <= datetime.now(UTC)
        activity = await _activity(todo_id)
        assert f"[{TodoActivityEvent.RUN_SKIPPED.value}]" in activity
        assert f"[{TodoActivityEvent.RUN_FAILED.value}]" not in activity
        assert f"[{TodoActivityEvent.RETRY_SCHEDULED.value}]" not in activity
        # The follow-up the user was having still answered them, in its chat.
        messages = (await _chat_of(mongo_db, todo_id))["messages"]
        assert [m["type"] for m in messages] == ["user", "bot", "bot"]
        assert messages[-1]["response"] == NARRATED


@pytest.mark.usefixtures("mongo_db")
class TestStoppingARunFromItsChat:
    async def test_a_stopped_run_is_logged_stopped_keeps_its_cards_and_is_not_a_success(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
        worker_pool: ArqRedis,
    ) -> None:
        """Regression: Stop ended the run as a silent success: no outcome logged, nothing delivered, schedule moved on as done."""
        due = datetime.now(UTC)
        todo_id = (
            await TrackedTodoService.create_tracked_todo(
                owner.user_id, TITLE, schedule=TodoUpdate(scheduled_at=due)
            )
        ).id
        conversation_id = await get_or_create_todo_conversation(owner.user_id, todo_id, TITLE)
        full = [
            {"type": "bot", "response": f"run {n}", "message_id": f"seed-{n}", "date": "2026"}
            for n in range(TODO_CONVERSATION_MAX_MESSAGES)
        ]
        await mongo_db["conversations"].update_one(
            {"conversation_id": conversation_id}, {"$set": {"messages": full}}
        )
        executor = prompt_reading(executor_run(REPORT))

        async with open_stack(executor=executor, comms=[NARRATED]) as stack:
            # The call after the card: its prompt is the first to hold the flowchart's output.
            after_the_card = executor.hold_calls_seeing(f"direction: {FLOWCHART['direction']}")
            with _paid():
                running = asyncio.create_task(
                    execute_tracked_todo({}, todo_id, scheduled_for=occurrence_stamp(due))
                )
                await after_the_card.reached.wait()
                (started,) = stack.pushed_of("executor.stream_started")
                stopped = await client.post(f"/api/v1/cancel-stream/{started['stream_id']}")
                after_the_card.released.set()
                result = await running

        assert stopped.json()["success"] is True
        assert result == f"cancelled:{todo_id}"
        activity = await _activity(todo_id)
        assert f"[{TodoActivityEvent.RUN_CANCELLED.value}] scheduled run stopped by the user" in (
            activity
        )
        assert f"[{TodoActivityEvent.RUN_FINISHED.value}]" not in activity
        assert f"[{TodoActivityEvent.RETRY_SCHEDULED.value}]" not in activity
        # Nothing reached the user: they stopped it.
        assert await mongo_db["notifications"].count_documents({"user_id": owner.user_id}) == 0
        # The cards it already streamed stay in the chat, which stays capped.
        messages = (await _chat_of(mongo_db, todo_id))["messages"]
        assert len(messages) == TODO_CONVERSATION_MAX_MESSAGES
        assert messages[-1]["message_id"] == started["task_id"]
        assert "create_flowchart" in _card_tool_names(messages[-1])


@pytest.mark.usefixtures("mongo_db")
class TestTheChatKeepsOnlyItsNewestMessages:
    async def test_a_full_chat_drops_its_oldest_message_for_the_report(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)
        conversation_id = await get_or_create_todo_conversation(owner.user_id, todo_id, TITLE)
        seeded = [
            {"type": "bot", "response": f"run {n}", "message_id": f"seed-{n}", "date": "2026"}
            for n in range(TODO_CONVERSATION_MAX_MESSAGES)
        ]
        await mongo_db["conversations"].update_one(
            {"conversation_id": conversation_id}, {"$set": {"messages": seeded}}
        )

        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]):
            await _run(todo_id, owner)

        messages = (await _chat_of(mongo_db, todo_id))["messages"]
        assert len(messages) == TODO_CONVERSATION_MAX_MESSAGES
        assert messages[0]["response"] == "run 1"
        assert messages[-1]["response"] == REPORT


@pytest.mark.usefixtures("mongo_db")
class TestTheChatFollowsItsTodo:
    async def test_renaming_the_todo_renames_its_chat(
        self, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase, client: AsyncClient
    ) -> None:
        """Regression: the chat kept the todo's first title, so its tab still named the old one."""
        todo_id = await _new_tracked_todo(owner)
        conversation_id = (await client.post(f"/api/v1/todos/{todo_id}/conversation")).json()[
            "conversation_id"
        ]

        renamed = await client.put(f"/api/v1/todos/{todo_id}", json={"title": RENAMED})

        assert renamed.status_code == 200
        synced = await client.post(
            "/api/v1/conversations/batch-sync",
            json={"conversations": [{"conversation_id": conversation_id}]},
        )
        (row,) = synced.json()["conversations"]
        assert row["description"] == RENAMED

    async def test_a_completed_todo_still_opens_its_chat_with_its_history(
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

        completed = await client.put(f"/api/v1/todos/{todo_id}", json={"completed": True})
        opened = await client.post(f"/api/v1/todos/{todo_id}/conversation")

        assert completed.json()["completed"] is True
        assert opened.json() == {"conversation_id": conversation_id}
        assert [m["response"] for m in (await _chat_of(mongo_db, todo_id))["messages"]] == [REPORT]

    async def test_starring_the_chat_never_lists_it(
        self, owner: AuthenticatedUser, client: AsyncClient
    ) -> None:
        todo_id = await _new_tracked_todo(owner)
        conversation_id = (await client.post(f"/api/v1/todos/{todo_id}/conversation")).json()[
            "conversation_id"
        ]

        starred = await client.put(
            f"/api/v1/conversations/{conversation_id}/star", json={"starred": True}
        )
        listed = await client.get("/api/v1/conversations", params={"limit": 50})

        assert starred.status_code == 200
        assert conversation_id not in [c["conversation_id"] for c in listed.json()["conversations"]]

    async def test_a_run_the_user_is_not_told_of_still_keeps_its_report_in_the_chat(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        created = await TrackedTodoService.create_tracked_todo(
            owner.user_id, TITLE, notify_on_run=False
        )

        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]):
            await _run(created.id, owner)

        assert [m["response"] for m in (await _chat_of(mongo_db, created.id))["messages"]] == [
            REPORT
        ]
        assert await mongo_db["notifications"].count_documents({"user_id": owner.user_id}) == 0

    async def test_a_run_comms_keeps_quiet_about_still_keeps_its_report_in_the_chat(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(
            executor=executor_run(REPORT), comms=["<SILENCE>nothing changed</SILENCE>"]
        ):
            await _run(todo_id, owner)

        assert [m["response"] for m in (await _chat_of(mongo_db, todo_id))["messages"]] == [REPORT]
        assert await mongo_db["notifications"].count_documents({"user_id": owner.user_id}) == 0
        assert "kept quiet: nothing changed" in await _activity(todo_id)


@pytest.mark.usefixtures("mongo_db")
class TestNoChatOutlivesItsTodo:
    async def test_bulk_deleting_a_parent_deletes_its_and_its_sub_todos_chats(
        self, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase, client: AsyncClient
    ) -> None:
        parent = await _new_tracked_todo(owner)
        child = (
            await TrackedTodoService.create_tracked_todo(
                owner.user_id, "Watch the migrations", parent_todo_id=parent
            )
        ).id
        for todo_id in (parent, child):
            assert (await client.post(f"/api/v1/todos/{todo_id}/conversation")).status_code == 200

        deleted = await client.request("DELETE", "/api/v1/todos/bulk", json=[parent])

        assert deleted.status_code == 200
        assert set(deleted.json()["success"]) == {parent, child}
        assert await mongo_db["conversations"].count_documents({"user_id": owner.user_id}) == 0

    async def test_deleting_the_todo_mid_run_resurrects_no_chat(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        todo_id = await _new_tracked_todo(owner)
        executor = prompt_reading(executor_run(REPORT))

        async with open_stack(executor=executor, comms=[NARRATED]):
            mid_run = executor.hold_calls_seeing("Bound 1 tools")
            running = asyncio.create_task(_run(todo_id, owner))
            await mid_run.reached.wait()
            assert (await client.delete(f"/api/v1/todos/{todo_id}")).status_code == 204
            mid_run.released.set()
            await running

        assert await mongo_db["conversations"].count_documents({"user_id": owner.user_id}) == 0
        listed = await client.get("/api/v1/conversations", params={"limit": 50})
        assert listed.json()["conversations"] == []

    async def test_deleting_all_chats_keeps_the_todos_chats(
        self, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase, client: AsyncClient
    ) -> None:
        """Regression: "Delete all conversations" also wiped every hidden todo chat, mid-run or awaiting an approval."""
        todo_id = await _new_tracked_todo(owner)
        todo_chat = (await client.post(f"/api/v1/todos/{todo_id}/conversation")).json()[
            "conversation_id"
        ]

        nothing_listed = await client.delete("/api/v1/conversations")
        await create_conversation_service(
            ConversationModel(conversation_id=str(uuid4()), description="a chat"), owner
        )
        deleted = await client.delete("/api/v1/conversations")

        # The sidebar was empty, so there was nothing to delete.
        assert nothing_listed.status_code == 404
        assert deleted.status_code == 200
        (kept,) = await mongo_db["conversations"].find({"user_id": owner.user_id}).to_list(None)
        assert kept["conversation_id"] == todo_chat

    async def test_another_user_can_neither_read_nor_star_the_chat(
        self,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
        test_app: FastAPI,
    ) -> None:
        todo_id = await _new_tracked_todo(owner)
        conversation_id = (await client.post(f"/api/v1/todos/{todo_id}/conversation")).json()[
            "conversation_id"
        ]

        with _signed_in_as(test_app, FAKE_USER_2):
            read = await client.get(f"/api/v1/conversations/{conversation_id}")
            synced = await client.post(
                "/api/v1/conversations/batch-sync",
                json={"conversations": [{"conversation_id": conversation_id}]},
            )
            starred = await client.put(
                f"/api/v1/conversations/{conversation_id}/star", json={"starred": True}
            )

        assert read.status_code == 404
        assert synced.json()["conversations"] == []
        assert starred.status_code == 404
        chat = await _chat_of(mongo_db, todo_id)
        assert not chat.get("starred")
