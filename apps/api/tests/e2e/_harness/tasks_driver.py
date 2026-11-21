"""The user's actions on tasks, implemented on today's /todos and /workflows system.

Journeys speak only through this driver and tasks_views, so the same journey
files can later run against /tasks by swapping this module's implementation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from datetime import datetime
import re
from typing import Any
from uuid import uuid4

from arq.connections import ArqRedis
from arq.constants import default_queue_name, job_key_prefix
from arq.jobs import JobDef
from httpx import AsyncClient, Response

from app.agents.tools.tracked_todo_tools import create_tracked_todo
from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX
from app.constants.todos import FAILED_LABEL, GAIA_TRACKED_LABEL, TodoActivityEvent
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.models.message_models import MessageRequestWithHistory
from app.models.payment_models import PlanType
from app.services.chat import stream as chat_stream
from app.utils.auth_utils import require_owner
from app.worker import TASK_FUNCTIONS
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import call
from tests.e2e._harness.tasks_views import (
    Asks,
    Breaks,
    ChatLine,
    Counts,
    Delivered,
    Finishes,
    GaiaRun,
    KeepsHolding,
    OpensSubtasks,
    Reports,
    RunOutcome,
    RunView,
    Subtask,
    TaskNotFoundError,
    TaskView,
)
from tests.e2e._harness.transcript import Transcript
from tests.e2e._harness.turn_queue import TurnQueue

TODOS = "/api/v1/todos"
NOTIFICATIONS = "/api/v1/notifications"
#: When a one-off GAIA task first looks at its work, as a user handing it over leaves it.
FIRST_LOOK = "1h"
#: What GAIA says in the chat while it picks the work up.
ON_IT = "On it."
#: When GAIA checks back on a question it asked.
QUESTION_EXPIRES = "1d"
_ACTIVITY_LINE = re.compile(r"^- .*?\[(?P<event>[a-z_]+)\] ?(?P<detail>.*)$")
_RUN_EVENTS = {
    TodoActivityEvent.RUN_FINISHED.value: RunOutcome.SUCCEEDED,
    TodoActivityEvent.RUN_FAILED.value: RunOutcome.FAILED,
    TodoActivityEvent.RUN_SKIPPED.value: RunOutcome.SKIPPED,
}
#: The worker's own job functions, wrapped as the worker registers them.
_JOBS: Mapping[str, Callable[..., Awaitable[object]]] = {
    getattr(f, "name", getattr(f, "__name__", "")): getattr(f, "coroutine", f)
    for f in TASK_FUNCTIONS
}
_RUN_JOBS = ("execute_tracked_todo", "resume_tracked_todo", "execute_workflow_by_id")


def _ok(response: Response) -> Any:
    if response.status_code == 404:
        raise TaskNotFoundError(response.text)
    assert response.is_success, (
        f"{response.request.method} {response.request.url}: {response.status_code} {response.text}"
    )
    return response.json()


def _task_view(body: dict[str, Any]) -> TaskView:
    return TaskView(
        id=body["id"],
        title=body["title"],
        done=body["completed"],
        due=datetime.fromisoformat(body["due_date"]) if body.get("due_date") else None,
        subtasks=tuple(
            Subtask(id=s["id"], title=s["title"], done=s["completed"]) for s in body["subtasks"]
        ),
        by_gaia=GAIA_TRACKED_LABEL in body["labels"],
        failed=FAILED_LABEL in body["labels"],
        parent_id=body.get("parent_todo_id"),
        open_children=body.get("sub_todo_count", 0),
        pending_approval=body.get("pending_approval") is not None,
    )


class TasksDriver:
    """A signed-in user's hands on their tasks, and their eyes on what came of them."""

    def __init__(
        self,
        client: AsyncClient,
        *,
        user_id: str,
        pool: ArqRedis,
        executor: TurnQueue,
        comms: TurnQueue,
    ) -> None:
        self._client = client
        self._user_id = user_id
        self._pool = pool
        self._executor = executor
        self._comms = comms
        self._one_offs: set[str] = set()

    # The account.

    async def subscribe(self) -> None:
        """Put the user on the paid plan, as a finished checkout leaves its plan cache."""
        await redis_cache.set(
            f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{self._user_id}", {"plan_type": PlanType.PRO.value}
        )

    async def let_subscription_lapse(self) -> None:
        await redis_cache.delete(f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{self._user_id}")

    # To-dos the user does themselves.

    async def create_todo(self, title: str, *, due: datetime | None = None) -> TaskView:
        payload: dict[str, Any] = {"title": title}
        if due is not None:
            payload["due_date"] = due.isoformat()
        return _task_view(_ok(await self._client.post(TODOS, json=payload)))

    async def edit(
        self, task_id: str, *, title: str | None = None, due: datetime | None = None
    ) -> TaskView:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if due is not None:
            payload["due_date"] = due.isoformat()
        return _task_view(_ok(await self._client.put(f"{TODOS}/{task_id}", json=payload)))

    async def complete(self, task_id: str) -> TaskView:
        return _task_view(
            _ok(await self._client.put(f"{TODOS}/{task_id}", json={"completed": True}))
        )

    async def reopen(self, task_id: str) -> TaskView:
        return _task_view(
            _ok(await self._client.put(f"{TODOS}/{task_id}", json={"completed": False}))
        )

    async def delete(self, task_id: str) -> None:
        response = await self._client.delete(f"{TODOS}/{task_id}")
        assert response.status_code == 204, response.text

    async def add_subtask(self, task_id: str, title: str) -> TaskView:
        return _task_view(
            _ok(await self._client.post(f"{TODOS}/{task_id}/subtasks", json={"title": title}))
        )

    async def rename_subtask(self, task_id: str, subtask_id: str, title: str) -> TaskView:
        return _task_view(
            _ok(
                await self._client.put(
                    f"{TODOS}/{task_id}/subtasks/{subtask_id}", json={"title": title}
                )
            )
        )

    async def tick_subtask(self, task_id: str, subtask_id: str) -> TaskView:
        return _task_view(
            _ok(await self._client.post(f"{TODOS}/{task_id}/subtasks/{subtask_id}/toggle"))
        )

    # Work handed to GAIA.

    async def hand_to_gaia(self, title: str, *, notify: bool = True) -> TaskView:
        """Hand GAIA a one-off task, as its create tool does when the user asks in chat."""
        before = {t.id for t in await self._gaia_tasks()}
        said = await create_tracked_todo.ainvoke(
            {
                "title": title,
                "waiting_on": "time",
                "scheduled_at": FIRST_LOOK,
                "notify_on_run": notify,
            },
            config={"configurable": {"user_id": self._user_id}},
        )
        (created,) = [t for t in await self._gaia_tasks() if t.id not in before] or [None]
        assert created is not None, f"GAIA did not take the task on: {said}"
        self._one_offs.add(created.id)
        return created

    async def run_due(self, task_id: str, *runs: GaiaRun) -> list[str]:
        """Let the task's armed runs fire, GAIA doing each run as scripted; return what each job said."""
        down = Breaks() in runs
        assert not down or len(runs) == 1, "a run where the provider is down is scripted alone"
        for run in runs:
            self._queue_tracked(task_id, run)
        with self._executor.provider_down() if down else nullcontext():
            outcomes = [await self._run(job) for job in await self._armed(task_id)]
        self._all_turns_taken()
        return outcomes

    def _all_turns_taken(self) -> None:
        """Fail unless GAIA was asked for exactly the turns the journey scripted."""
        for model in (self._executor, self._comms):
            assert not model.unscripted, f"GAIA took a turn nothing scripted: {model.unscripted}"
        assert self._executor.pending == 0, "GAIA was scripted for more work than it was asked for"
        assert self._comms.pending == 0, "a scripted reply or delivery was never asked for"

    def _queue_tracked(self, task_id: str, run: GaiaRun) -> None:
        match run:
            case Finishes(report):
                self._executor.then(
                    [call("complete_tracked_todo", {"todo_id": task_id, "summary": report}), report]
                )
                self._comms.then([report])
            case KeepsHolding(report):
                self._executor.then(
                    [
                        call(
                            "update_tracked_todo",
                            {"todo_id": task_id, "scheduled_at": QUESTION_EXPIRES},
                        ),
                        report,
                    ]
                )
                self._comms.then([report])
            case Reports(report):
                # A one-off run that neither closes nor re-arms its task is nudged once to.
                nudged = task_id in self._one_offs
                self._executor.then([report, report] if nudged else [report])
                self._comms.then([report])
            case Asks(question, if_no_reply, default):
                ask: dict[str, Any] = {
                    "todo_id": task_id,
                    "waiting_on": "user",
                    "question": question,
                    "if_no_reply": if_no_reply.value,
                    "scheduled_at": QUESTION_EXPIRES,
                }
                if default is not None:
                    ask["default_action"] = default
                self._executor.then([call("update_tracked_todo", ask), question])
                self._comms.then([question])
            case OpensSubtasks(titles, report):
                self._executor.then(
                    [
                        *(
                            call(
                                "create_tracked_todo",
                                {
                                    "title": title,
                                    "parent_todo_id": task_id,
                                    "waiting_on": "time",
                                    "scheduled_at": FIRST_LOOK,
                                },
                                call_id=f"tc_sub_{i}",
                            )
                            for i, title in enumerate(titles)
                        ),
                        call(
                            "update_tracked_todo",
                            {"todo_id": task_id, "waiting_on": "sub_todos", "scheduled_at": "3d"},
                        ),
                        report,
                    ]
                )
                self._comms.then([report])
            case Breaks():
                pass

    async def answer(self, task_id: str, reply: str, then: GaiaRun) -> None:
        """Reply in the task's chat, GAIA picking the task up from the reply."""
        conversation_id = _ok(await self._client.post(f"{TODOS}/{task_id}/conversation"))[
            "conversation_id"
        ]
        self._comms.then([call("call_executor", {"task": reply}, call_id="tc_answer"), ON_IT])
        self._queue_tracked(task_id, then)
        stream_id = str(uuid4())
        await stream_manager.start_stream(
            stream_id=stream_id, conversation_id=conversation_id, user_id=self._user_id
        )
        await chat_stream.run_chat_stream_background(
            stream_id=stream_id,
            body=MessageRequestWithHistory(
                message=reply,
                messages=[{"role": "user", "content": reply}],
                conversation_id=conversation_id,
            ),
            user=await require_owner(self._user_id),
            conversation_id=conversation_id,
        )
        transcript = Transcript.from_sse(
            "".join([chunk async for chunk in stream_manager.subscribe_stream(stream_id)])
        )
        assert transcript.is_done, "the reply's chat turn never finished"
        await drain_background_runs()
        self._all_turns_taken()

    async def _armed(self, task_id: str) -> list[JobDef]:
        jobs = sorted(await self._pool.queued_jobs(), key=lambda j: j.score)
        return [j for j in jobs if j.function in _RUN_JOBS and j.args and j.args[0] == task_id]

    async def _run(self, job: JobDef) -> str:
        """Run a queued job as the worker would, taking it off the queue first."""
        await self._pool.zrem(default_queue_name, job.job_id)
        await self._pool.delete(job_key_prefix + job.job_id)
        return str(await _JOBS[job.function]({"job_id": job.job_id}, *job.args, **job.kwargs))

    # What the user sees.

    async def get(self, task_id: str) -> TaskView | None:
        response = await self._client.get(f"{TODOS}/{task_id}")
        if response.status_code == 404:
            return None
        return _task_view(_ok(response))

    async def open_list(self) -> list[TaskView]:
        """Return the open tasks list, in the order the list API returns it."""
        return await self._list(completed="false")

    async def overdue(self) -> list[TaskView]:
        return await self._list(overdue="true")

    async def completed_list(self) -> list[TaskView]:
        return await self._list(completed="true")

    async def counts(self) -> Counts:
        body = _ok(await self._client.get(f"{TODOS}/counts"))
        return Counts(today=body["today"], overdue=body["overdue"], completed=body["completed"])

    async def runs(self, task_id: str) -> list[RunView]:
        """Return the task's run history, oldest first, as its activity log records each run."""
        return [
            RunView(outcome=_RUN_EVENTS[event], reason=detail or None)
            for event, detail in await self._activity(task_id)
            if event in _RUN_EVENTS
        ]

    async def delivered(self) -> list[Delivered]:
        """Return every message GAIA delivered to the user in the app, oldest first."""
        body = _ok(await self._client.get(NOTIFICATIONS, params={"limit": 100}))
        return [
            Delivered(title=n["content"]["title"], body=n["content"]["body"], channel="inapp")
            for n in reversed(body["notifications"])
        ]

    async def chat(self, task_id: str) -> list[ChatLine]:
        """Return the task's own chat as the user opens it from the task, oldest first."""
        conversation_id = _ok(await self._client.post(f"{TODOS}/{task_id}/conversation"))[
            "conversation_id"
        ]
        synced = _ok(
            await self._client.post(
                "/api/v1/conversations/batch-sync",
                json={"conversations": [{"conversation_id": conversation_id}]},
            )
        )
        (row,) = synced["conversations"]
        return [
            ChatLine(by_user=m["type"] == "user", text=m["response"])
            for m in row["messages"]
            if m["response"]
        ]

    async def _activity(self, task_id: str) -> list[tuple[str, str]]:
        body = _ok(await self._client.get(f"{TODOS}/{task_id}/canvas"))
        return [
            (m["event"], m["detail"])
            for line in body["activity"].splitlines()
            if (m := _ACTIVITY_LINE.match(line))
        ]

    async def _gaia_tasks(self) -> list[TaskView]:
        return await self._list(labels=GAIA_TRACKED_LABEL)

    async def _list(self, **params: str) -> list[TaskView]:
        body = _ok(await self._client.get(TODOS, params={"mode": "text", **params}))
        return [_task_view(item) for item in body["data"]]
