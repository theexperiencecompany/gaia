"""The user's actions on tasks, implemented on today's /todos and /workflows system.

Journeys speak only through this driver and tasks_views, so the same journey
files can later run against /tasks by swapping this module's implementation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from uuid import uuid4

from arq.connections import ArqRedis
from arq.constants import default_queue_name, job_key_prefix
from arq.jobs import JobDef
from httpx import AsyncClient, Response
import time_machine

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
    KeepsWaiting,
    NeedsApproval,
    OpensSubtasks,
    RepeatingTaskView,
    Reports,
    RunOutcome,
    RunView,
    Subtask,
    TaskNotFoundError,
    TaskView,
)
from tests.e2e._harness.transcript import Transcript
from tests.e2e._harness.turn_queue import APPROVAL_ID_FROM_PROMPT, TurnQueue

TODOS = "/api/v1/todos"
WORKFLOWS = "/api/v1/workflows"
#: How long after its armed time the worker picks a job up.
JOB_PICKUP_DELAY = timedelta(seconds=1)
#: How long after the first a duplicate delivery of the same job arrives.
DUPLICATE_DELIVERY_DELAY = timedelta(minutes=5)
NOTIFICATIONS = "/api/v1/notifications"
#: When a one-off GAIA task first looks at its work, as a user handing it over leaves it.
FIRST_LOOK = "1h"
HIL_PREFERENCES = "/api/v1/approvals/preferences"
#: The action a NeedsApproval run reaches: pure, and outside the executor's initial tools.
GATED_ACTION = "create_flowchart"
GATED_ACTION_ARGS = {"description": "the plan's three steps", "direction": "LR"}
#: The card an approved action leaves in the chat once GAIA has taken it.
APPROVED_ACTION_CARD = "approve"
_REDEEM = {
    "task_description": "take the approved action",
    "tool_name": "approve",
    "data": {"id": APPROVAL_ID_FROM_PROMPT},
}
#: A run's answer to the playbook check when its calls depend on what it finds.
_DECLINE_PLAYBOOK = call(
    "decline_playbook",
    {"kind": "unstable_discovery", "reason": "the stories differ every day"},
    call_id="tc_decline",
)
#: What GAIA says in the chat while it picks the work up.
ON_IT = "On it."
#: When GAIA checks back on a question it asked.
QUESTION_EXPIRES = "1d"
_ACTIVITY_LINE = re.compile(r"^- .*?\[(?P<event>[a-z_]+)\] ?(?P<detail>.*)$")
_WORKFLOW_RUN_STATUS = {
    "success": RunOutcome.SUCCEEDED,
    "failed": RunOutcome.FAILED,
    "skipped": RunOutcome.SKIPPED,
}
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
        next_run=datetime.fromisoformat(body["scheduled_at"]) if body.get("scheduled_at") else None,
    )


def _repeating_view(body: dict[str, Any]) -> RepeatingTaskView:
    workflow = body["workflow"]
    next_run = workflow["trigger_config"].get("next_run")
    return RepeatingTaskView(
        id=workflow["id"],
        title=workflow["title"],
        active=workflow["activated"],
        next_run=datetime.fromisoformat(next_run) if next_run else None,
        paused_reason=workflow.get("deactivated_reason"),
    )


async def _execute(job: JobDef, *, after: timedelta) -> str:
    """Run a job's function as the worker does, the clock moved to when it was armed for plus after."""
    due = datetime.fromtimestamp(job.score / 1000, UTC) + after
    with time_machine.travel(max(due, datetime.now(UTC)), tick=True):
        said = str(await _JOBS[job.function]({"job_id": job.job_id}, *job.args, **job.kwargs))
        # The run's delivery finishes in the background, still at that time.
        await drain_background_runs()
        return said


def _is_workflow(task_id: str) -> bool:
    return task_id.startswith("wf_")


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
        self._last_fired: JobDef | None = None

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
        return created

    async def run_due(self, task_id: str, run: GaiaRun) -> str:
        """Let time pass to the task's next armed run and fire it, GAIA working as scripted.

        Returns what the worker said of the job, for a journey that checks it was skipped.
        """
        armed = await self._armed(task_id)
        assert armed, f"nothing is armed to run task {task_id}"
        await self._queue_run(task_id, run)
        with self._executor.provider_down() if isinstance(run, Breaks) else nullcontext():
            outcome = await self._run(armed[0])
        self._all_turns_taken()
        return outcome

    async def has_run_armed(self, task_id: str) -> bool:
        """Whether anything will run the task again."""
        return bool(await self._armed(task_id))

    def _all_turns_taken(self) -> None:
        """Fail unless GAIA was asked for exactly the turns the journey scripted."""
        for model in (self._executor, self._comms):
            assert not model.unscripted, f"GAIA took a turn nothing scripted: {model.unscripted}"
        assert self._executor.pending == 0, "GAIA was scripted for more work than it was asked for"
        assert self._comms.pending == 0, "a scripted reply or delivery was never asked for"

    async def _queue_tracked(self, task_id: str, run: GaiaRun) -> None:
        """Queue GAIA's turns for one run of a tracked todo, and comms' write-up when it is delivered."""
        todo = _ok(await self._client.get(f"{TODOS}/{task_id}"))
        delivered = todo["notify_on_run"]
        # A one-off run that neither closes nor re-arms its todo is nudged once to.
        one_off = not todo["recurrence"] and not todo["trigger_subscriptions"]

        def tell(text: str) -> None:
            if delivered:
                self._comms.then([text])

        match run:
            case Finishes(report):
                self._executor.then(
                    [call("complete_tracked_todo", {"todo_id": task_id, "summary": report}), report]
                )
                tell(report)
            case KeepsWaiting(report):
                self._executor.then(
                    [
                        call(
                            "update_tracked_todo",
                            {"todo_id": task_id, "scheduled_at": QUESTION_EXPIRES},
                        ),
                        report,
                    ]
                )
                tell(report)
            case Reports(report):
                self._executor.then([report, report] if one_off else [report])
                tell(report)
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
                tell(question)
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
                tell(report)
            case NeedsApproval(asking):
                self._executor.then(
                    [
                        call(
                            "retrieve_tools",
                            {"exact_tool_names": [GATED_ACTION]},
                            call_id="tc_find",
                        ),
                        call(GATED_ACTION, GATED_ACTION_ARGS, call_id="tc_gated"),
                        *([asking, asking] if one_off else [asking]),
                    ]
                )
                tell(asking)
            case Breaks():
                pass

    async def answer(self, task_id: str, reply: str, then: GaiaRun) -> None:
        """Reply in the task's chat, GAIA picking the task up from the reply."""
        conversation_id = _ok(await self._client.post(f"{TODOS}/{task_id}/conversation"))[
            "conversation_id"
        ]
        self._comms.then([call("call_executor", {"task": reply}, call_id="tc_answer"), ON_IT])
        await self._queue_tracked(task_id, then)
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

    # Tasks GAIA repeats.

    async def create_repeating_task(
        self, title: str, brief: str, *, cron: str, notify: bool = True
    ) -> RepeatingTaskView:
        """Create a task GAIA runs on a schedule, from the task form."""
        created = _ok(
            await self._client.post(
                WORKFLOWS,
                json={
                    "title": title,
                    "prompt": brief,
                    "trigger_config": {
                        "type": "schedule",
                        "cron_expression": cron,
                        "timezone": "UTC",
                    },
                    "steps": [],
                    "notify_on_completion": notify,
                },
            )
        )
        return _repeating_view(created)

    async def reschedule(self, task_id: str, *, cron: str) -> RepeatingTaskView:
        current = _ok(await self._client.get(f"{WORKFLOWS}/{task_id}"))["workflow"]
        trigger = {**current["trigger_config"], "cron_expression": cron}
        return _repeating_view(
            _ok(await self._client.put(f"{WORKFLOWS}/{task_id}", json={"trigger_config": trigger}))
        )

    async def edit_brief(self, task_id: str, brief: str) -> RepeatingTaskView:
        return _repeating_view(
            _ok(await self._client.put(f"{WORKFLOWS}/{task_id}", json={"prompt": brief}))
        )

    async def get_repeating(self, task_id: str) -> RepeatingTaskView:
        return _repeating_view(_ok(await self._client.get(f"{WORKFLOWS}/{task_id}")))

    async def fire_every_armed(self, task_id: str, run: GaiaRun) -> None:
        """Fire every run ever armed for the task, stale ones included, GAIA doing one run as scripted."""
        await self._queue_run(task_id, run)
        for job in await self._armed(task_id):
            await self._run(job)
        self._all_turns_taken()

    async def fire_again(self, task_id: str) -> None:
        """Deliver the task's last fired job a second time, as a duplicate delivery would."""
        assert self._last_fired is not None, "nothing was fired yet"
        await _execute(self._last_fired, after=DUPLICATE_DELIVERY_DELAY)
        self._all_turns_taken()

    async def _queue_run(self, task_id: str, run: GaiaRun) -> None:
        if not _is_workflow(task_id):
            await self._queue_tracked(task_id, run)
            return
        match run:
            case Reports(report):
                self._comms.then(
                    [call("call_executor", {"task": f"run {task_id}"}, call_id="tc_run"), ON_IT]
                )
                self._executor.then([_DECLINE_PLAYBOOK, report])
                workflow = _ok(await self._client.get(f"{WORKFLOWS}/{task_id}"))["workflow"]
                if workflow["notify_on_completion"]:
                    self._comms.then([report])
            case _:
                raise NotImplementedError(f"a repeating task cannot be scripted to {run}")

    async def ask_before_acting(self) -> None:
        """Set the user's approval settings to ask before the action GAIA takes in NeedsApproval."""
        _ok(
            await self._client.put(
                HIL_PREFERENCES,
                json={"mode": "always_ask", "tool_overrides": {GATED_ACTION: True}},
            )
        )

    async def approve(self, task_id: str, report: str) -> None:
        """Approve the action the task waits on; GAIA takes it and reports."""
        self._executor.then([call("execute", _REDEEM, call_id="tc_redeem"), report, report, report])
        await self._decide(task_id, {"decision": "approve"}, report, runs=2)

    async def deny(self, task_id: str, report: str) -> None:
        """Deny the action the task waits on; GAIA skips it and reports."""
        self._executor.then([report, report])
        await self._decide(task_id, {"decision": "deny", "feedback": "not now"}, report, runs=1)

    async def _decide(
        self, task_id: str, verdict: dict[str, str], report: str, *, runs: int
    ) -> None:
        todo = _ok(await self._client.get(f"{TODOS}/{task_id}"))
        pending = todo["pending_approval"]
        assert pending is not None, "the task waits on no approval"
        if todo["notify_on_run"]:
            self._comms.then([report] * runs)
        _ok(
            await self._client.post(
                f"/api/v1/approvals/{pending['approval_id']}/decision", json=verdict
            )
        )
        await drain_background_runs()
        for job in await self._armed(task_id):
            if job.function == "resume_tracked_todo":
                await self._run(job)
        await drain_background_runs()
        self._all_turns_taken()

    async def _armed(self, task_id: str) -> list[JobDef]:
        jobs = sorted(await self._pool.queued_jobs(), key=lambda j: j.score)
        return [j for j in jobs if j.function in _RUN_JOBS and j.args and j.args[0] == task_id]

    async def _run(self, job: JobDef) -> str:
        """Run a queued job as the worker would, taking it off the queue first."""
        self._last_fired = job
        await self._pool.zrem(default_queue_name, job.job_id)
        await self._pool.delete(job_key_prefix + job.job_id)
        return await _execute(job, after=JOB_PICKUP_DELAY)

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

    async def subtasks_of(self, task_id: str) -> list[TaskView]:
        """Return the sub-tasks listed under a task, open and done."""
        return await self._list(parent_todo_id=task_id)

    async def runs(self, task_id: str) -> list[RunView]:
        """Return the task's run history, oldest first, as its page lists each run."""
        if _is_workflow(task_id):
            body = _ok(await self._client.get(f"{WORKFLOWS}/{task_id}/executions"))
            return [
                RunView(outcome=_WORKFLOW_RUN_STATUS[e["status"]], reason=e.get("summary"))
                for e in reversed(body["executions"])
            ]
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
            ChatLine(
                by_user=m["type"] == "user",
                text=m["response"],
                cards=tuple(
                    str((entry.get("data") or {}).get("tool_name", entry.get("tool_name")))
                    for entry in m.get("tool_data") or []
                ),
            )
            for m in row["messages"]
            if m["response"] or m.get("tool_data")
        ]

    async def approved_actions_taken(self, task_id: str) -> int:
        """Count the approved actions the task's chat shows GAIA took, one card each."""
        return sum(line.cards.count(APPROVED_ACTION_CARD) for line in await self.chat(task_id))

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
