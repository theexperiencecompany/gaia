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
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import (
    AbstractContextManager,
    contextmanager,
)
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from arq.connections import ArqRedis
from bson import ObjectId
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import PrivateAttr
import pytest

from app.agents.core.background.todo_run import TodoRunFailedError
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.todos import (
    GAIA_TRACKED_LABEL,
    TodoActivityEvent,
    TodoWakeKind,
    WaitingOn,
)
from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.todos import todo_repository
from app.models.chat_models import ConversationModel, ConversationSource
from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import (
    Entry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    TodoWoke,
    UserMessage,
    WorkFinished,
    WorkOutcome,
)
from app.models.conversation_send_models import SendMessageRequest
from app.models.hil_models import HILPreferences
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerOrigin,
    TriggerSubscription,
)
from app.models.user_models import AuthenticatedUser
from app.services.conversation.event_stream import replay_from_log
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.send import submit_message
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
from tests.e2e._harness.graph_run import StreamingScriptedModel, call, streaming_model
from tests.e2e._harness.step_stack import OpenStack
from tests.helpers import stored_conversation, worker_redis_url

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("conversation_indexes", "offline_todo_seams"),
]

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


class FailingModel(StreamingScriptedModel):
    """A model whose provider errors on every call, the way an outage does."""

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise RuntimeError("the model provider is down")
        yield  # pragma: no cover — makes this an async generator, as the real one is

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the model provider is down")


def _daily_watch() -> TodoUpdate:
    """Return a valid open state: a daily watch, whose recurrence wakes it so no run must re-arm it."""
    return TodoUpdate(recurrence="daily", scheduled_at=datetime.now(UTC) + timedelta(days=1))


async def _new_tracked_todo(owner: AuthenticatedUser, title: str = TITLE) -> str:
    created = await TrackedTodoService.create_tracked_todo(
        owner.user_id, title, schedule=_daily_watch()
    )
    return created.todo.id


async def _new_due_tracked_todo(owner: AuthenticatedUser, due: datetime) -> str:
    """Create a todo whose next check the clock has reached: valid at creation, then due."""
    todo_id = await _new_tracked_todo(owner)
    await todo_repository.update(
        todo_id, user_id=owner.user_id, update=TodoUpdate(scheduled_at=due)
    )
    return todo_id


async def _run(todo_id: str, owner: AuthenticatedUser) -> None:
    """One run of the todo, through the worker's own run step."""
    doc = await todo_repository.get_by_id(todo_id)
    assert doc is not None
    await _execute_on_executor(doc, user_tz=Timezone.utc(), user_data=owner)


async def _chat_of(mongo_db: AsyncIOMotorDatabase, todo_id: str) -> dict[str, Any]:
    (chat,) = await mongo_db["conversations"].find({"todo_id": todo_id}).to_list(None)
    stored = await stored_conversation(mongo_db["conversations"], chat["conversation_id"])
    assert stored is not None
    return stored


async def _follow_up(conversation_id: str, owner: AuthenticatedUser, message: str) -> None:
    """One message the user sends in the chat, through the send route's service, answered by the step."""
    body = SendMessageRequest(message_id=str(uuid4()), text=message)
    await submit_message(conversation_id, owner, body, ConversationSource.WEB)
    await drain_background_runs()


async def _shown(mongo_db: AsyncIOMotorDatabase, todo_id: str) -> list[Entry]:
    """Return what a device opening the todo's chat receives: the events route's replay of its log."""
    (chat,) = await mongo_db["conversations"].find({"todo_id": todo_id}).to_list(None)
    log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
    frames = await replay_from_log(log, chat["conversation_id"], chat["user_id"], 0)
    return [f.frame.entry for f in frames if isinstance(f.frame, EntryFrame)]


def _finished(shown: Sequence[Entry]) -> list[WorkFinished]:
    """Each run's own end: its outcome, report and cards, as the chat shows its work."""
    return [entry for entry in shown if isinstance(entry, WorkFinished)]


def _reports(shown: Sequence[Entry]) -> list[str]:
    return [finished.report for finished in _finished(shown)]


def _write_ups(shown: Sequence[Entry]) -> list[Reply]:
    """Return what GAIA said in the chat: every reply, a run's write-up or an answer to the user."""
    return [entry for entry in shown if isinstance(entry, Reply)]


def _wake_kinds(shown: Sequence[Entry]) -> list[str]:
    return [entry.run.wake.kind.value for entry in shown if isinstance(entry, TodoWoke)]


def _card_tool_names(tool_data: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str((entry.get("data") or {}).get("tool_name", entry.get("tool_name")))
        for entry in tool_data
    ]


@pytest.mark.usefixtures("mongo_db")
class TestARunLandsInTheTodosOwnChat:
    async def test_the_run_streams_into_the_chat_and_its_report_stays_there(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]):
            await _run(todo_id, owner)

        chat = await _chat_of(mongo_db, todo_id)
        conversation_id = chat["conversation_id"]
        assert chat["user_id"] == owner.user_id
        assert chat["description"] == TITLE
        # Never an unread dot or a system section: the chat is reached from its todo.
        assert chat.get("is_unread") is False
        assert not chat.get("is_system_generated")

        # What woke the run leads the chat, then the work and the write-up that narrates it.
        shown = await _shown(mongo_db, todo_id)
        assert [entry.kind for entry in shown] == [
            "todo_woke",
            "work_started",
            "work_finished",
            "reply",
            "reply_settled",
        ]
        woke, _, finished, reply, settled = shown
        assert isinstance(woke, TodoWoke) and woke.run.wake.kind is TodoWakeKind.SCHEDULE
        assert isinstance(finished, WorkFinished)
        assert (finished.outcome, finished.report) == (WorkOutcome.DONE, REPORT)
        assert isinstance(reply, Reply) and reply.text == NARRATED
        assert reply.reply_id == finished.task_id
        assert "create_flowchart" in _card_tool_names(reply.tool_data)
        assert isinstance(settled, ReplySettled) and settled.outcome is ReplyOutcome.ANSWERED
        assert woke.id in settled.answers

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
        shown = await _shown(mongo_db, todo_id)
        assert _wake_kinds(shown) == [TodoWakeKind.SCHEDULE.value] * 2
        assert _reports(shown) == [REPORT, SECOND_REPORT]
        assert [reply.text for reply in _write_ups(shown)] == [NARRATED, NARRATED]
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

        shown = await _shown(mongo_db, todo_id)
        (failed,) = _finished(shown)
        assert failed.outcome is WorkOutcome.FAILED and failed.report
        (settled,) = [entry for entry in shown if isinstance(entry, ReplySettled)]
        assert settled.reply_id == failed.task_id and settled.outcome is ReplyOutcome.FAILED
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
        shown = await _shown(mongo_db, todo_id)
        assert _reports(shown) == [REPORT]
        assert [reply.text for reply in _write_ups(shown)] == [NARRATED]

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
        assert _reports(await _shown(mongo_db, todo_id)) == [REPORT]

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
            assert synced.status_code == 200
            assert _reports(await _shown(mongo_db, todo_id)) == [REPORT]

            await _follow_up(conversation_id, owner, "is it still green?")

        # The turn knew which todo "it" is: comms was shown this todo, bound to the turn.
        prompt = " ".join(str(m.content) for m in stack.comms_model.chat_messages_log[-1])
        assert "ACTIVE TODO" in prompt
        assert f"id: {todo_id}" in prompt

        shown = await _shown(mongo_db, todo_id)
        (asked,) = [entry for entry in shown if isinstance(entry, UserMessage)]
        assert asked.text == "is it still green?"
        assert _write_ups(shown)[-1].text == FOLLOW_UP_REPLY


THREAD_ID = "19a6c1f0d2e3b4a5"
RESOLVED_REPORT = (
    "Mads · single-user self-hosting licence · aryan@heygaia.io\n"
    "Aryan's reply confirmed the described setup is fine and Mads may proceed. "
    "No further reply or follow-up is needed; the thread is resolved."
)


async def _watching_thread_todo(owner: AuthenticatedUser) -> tuple[str, TriggerSubscription]:
    """Open a Gmail-thread todo watching its thread, as the inbox desk does.

    Its watch is stored as the real registration stores it; only the Composio call is skipped.
    """
    with patch("app.services.tracked_todo_service.watch_external_ref", new=AsyncMock()):
        todo_id = (
            await TrackedTodoService.create_tracked_todo(
                owner.user_id,
                "Mads · single-user self-hosting licence",
                external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=THREAD_ID),
                schedule=TodoUpdate(
                    waiting_on=WaitingOn.EVENT,
                    scheduled_at=datetime.now(UTC) + timedelta(days=3),
                ),
            )
        ).todo.id
    watch = TriggerSubscription(
        trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
        conditions=[
            SubscriptionCondition(
                field_name="thread_id", operator=ConditionOperator.EQUALS, value=THREAD_ID
            )
        ],
    )
    await todo_repository.add_trigger_subscription(
        todo_id, user_id=owner.user_id, subscription=watch
    )
    return todo_id, watch


@pytest.mark.usefixtures("mongo_db")
class TestAThreadTodoThatResolvesItself:
    @pytest.mark.regression
    async def test_its_report_is_judged_as_a_watchers_not_sent_as_a_one_time_answer(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        """Regression: completing a todo tore its watch down before delivery read it."""
        todo_id, watch = await _watching_thread_todo(owner)
        doc = await todo_repository.get_by_id(todo_id)
        assert doc is not None and doc.trigger_subscriptions
        reply = TriggerOrigin(
            subscription_id=watch.id,
            trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
            payload={"thread_id": THREAD_ID, "from_address": "aryan@heygaia.io"},
        )
        executor = [
            call(
                "retrieve_tools", {"exact_tool_names": ["complete_tracked_todo"]}, call_id="tc_find"
            ),
            call(
                "complete_tracked_todo",
                {"todo_id": todo_id, "summary": "Aryan confirmed; nothing left to answer."},
                call_id="tc_done",
            ),
            RESOLVED_REPORT,
        ]

        async with open_stack(executor=executor, comms=[RESOLVED_REPORT]) as stack:
            await _execute_on_executor(doc, user_tz=Timezone.utc(), user_data=owner, origin=reply)

        # The run closed the todo and, with it, its watch: what delivery reads afterwards.
        closed = await todo_repository.get_by_id(todo_id)
        assert closed is not None and closed.completed
        assert closed.trigger_subscriptions == []
        assert closed.activity_content is not None
        assert "stopped watching gmail_new_message (completed)" in closed.activity_content
        # Comms decided under the watcher's rule, which lets it keep quiet.
        delivery = " ".join(str(m.content) for m in stack.comms_model.chat_messages_log[-1])
        assert "Nobody asked for it just now" in delivery
        assert "This todo runs once" not in delivery


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
                owner.user_id, TITLE, notify_on_run=notify_on_run, schedule=_daily_watch()
            )
        ).todo.id
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
        (failed,) = _finished(await _shown(mongo_db, todo_id))
        async with open_stack(executor=[], comms=[FOLLOW_UP_REPLY]) as stack:
            await _follow_up(chat["conversation_id"], owner, "why did it fail?")

        prompt = " ".join(str(m.content) for m in stack.comms_model.chat_messages_log[-1])
        assert failed.report in prompt


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


async def ask_before(mongo_db: AsyncIOMotorDatabase, tool_name: str) -> None:
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
        await ask_before(mongo_db, "create_flowchart")
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

        shown = await _shown(mongo_db, todo_id)
        # The approval's resume says the approval woke it; the ticket run is no todo run.
        assert _wake_kinds(shown) == [TodoWakeKind.SCHEDULE.value, TodoWakeKind.APPROVAL.value]
        # The parked run, the ticket run the approval started, then the resume.
        assert _reports(shown) == [
            WAITING,
            DRAWN,
            # Two model messages, so two bubbles (HeldReplies, app/agents/core/held_replies.py).
            f"{RESUMED}{NEW_MESSAGE_BREAKER}{NOTHING_PENDING}",
        ]
        assert [reply.text for reply in _write_ups(shown)] == [NARRATED] * 3
        assert "approve" in _card_tool_names(_finished(shown)[1].tool_data)
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
        await ask_before(mongo_db, "create_flowchart")
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
        shown = await _shown(mongo_db, todo_id)
        parked, verdict = _reports(shown)
        assert parked == WAITING
        assert verdict.split(NEW_MESSAGE_BREAKER)[0] == SKIPPED
        assert [reply.text for reply in _write_ups(shown)] == [NARRATED] * 2
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
        todo_id = await _new_due_tracked_todo(owner, due)
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
        shown = await _shown(mongo_db, todo_id)
        (asked,) = [entry for entry in shown if isinstance(entry, UserMessage)]
        assert asked.text == "is it still green?"
        assert _wake_kinds(shown) == []
        assert _write_ups(shown)[-1].text == NARRATED


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
        todo_id = await _new_due_tracked_todo(owner, due)
        await get_or_create_todo_conversation(owner.user_id, todo_id, TITLE)
        executor = prompt_reading(executor_run(REPORT))

        async with open_stack(executor=executor, comms=[NARRATED]):
            # The call after the card: its prompt is the first to hold the flowchart's output.
            after_the_card = executor.hold_calls_seeing(f"direction: {FLOWCHART['direction']}")
            with _paid():
                running = asyncio.create_task(
                    execute_tracked_todo({}, todo_id, scheduled_for=occurrence_stamp(due))
                )
                await after_the_card.reached.wait()
                conversation_id = (await _chat_of(mongo_db, todo_id))["conversation_id"]
                stopped = await client.post(f"/api/v1/conversations/{conversation_id}/stop")
                after_the_card.released.set()
                result = await running

        assert stopped.status_code == 200, stopped.text
        assert result == f"cancelled:{todo_id}"
        activity = await _activity(todo_id)
        assert f"[{TodoActivityEvent.RUN_CANCELLED.value}] scheduled run stopped by the user" in (
            activity
        )
        assert f"[{TodoActivityEvent.RUN_FINISHED.value}]" not in activity
        assert f"[{TodoActivityEvent.RETRY_SCHEDULED.value}]" not in activity
        # Nothing reached the user: they stopped it.
        assert await mongo_db["notifications"].count_documents({"user_id": owner.user_id}) == 0
        # The cards it already streamed stay in the chat.
        (stopped_work,) = _finished(await _shown(mongo_db, todo_id))
        assert stopped_work.outcome is WorkOutcome.CANCELLED
        assert "create_flowchart" in _card_tool_names(stopped_work.tool_data)


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
        assert _reports(await _shown(mongo_db, todo_id)) == [REPORT]

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
            owner.user_id, TITLE, notify_on_run=False, schedule=_daily_watch()
        )

        async with open_stack(executor=executor_run(REPORT), comms=[NARRATED]):
            await _run(created.todo.id, owner)

        assert _reports(await _shown(mongo_db, created.todo.id)) == [REPORT]
        assert await mongo_db["notifications"].count_documents({"user_id": owner.user_id}) == 0

    async def test_a_run_comms_keeps_quiet_about_still_keeps_its_report_in_the_chat(
        self, open_stack: OpenStack, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        todo_id = await _new_tracked_todo(owner)

        async with open_stack(
            executor=executor_run(REPORT), comms=["<SILENCE>nothing changed</SILENCE>"]
        ):
            await _run(todo_id, owner)

        assert _reports(await _shown(mongo_db, todo_id)) == [REPORT]
        assert await mongo_db["notifications"].count_documents({"user_id": owner.user_id}) == 0
        assert "kept quiet: the write-up found it not worth a message" in await _activity(todo_id)


@pytest.mark.usefixtures("mongo_db")
class TestNoChatOutlivesItsTodo:
    async def test_bulk_deleting_a_parent_deletes_its_and_its_sub_todos_chats(
        self, owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase, client: AsyncClient
    ) -> None:
        parent = await _new_tracked_todo(owner)
        child = (
            await TrackedTodoService.create_tracked_todo(
                owner.user_id,
                "Watch the migrations",
                parent_todo_id=parent,
                schedule=_daily_watch(),
            )
        ).todo.id
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
