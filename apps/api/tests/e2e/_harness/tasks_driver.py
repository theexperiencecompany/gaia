"""The user's actions on tasks, implemented on today's /todos and /workflows system.

Journeys speak only through this driver and tasks_views, so the same journey
files can later run against /tasks by swapping this module's implementation.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import json
import re
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from arq.connections import ArqRedis
from arq.constants import default_queue_name, job_key_prefix
from arq.jobs import JobDef
from fastapi import BackgroundTasks
from httpx import AsyncClient, Response
from pydantic import BaseModel
import time_machine

from app.agents.tools.tracked_todo_tools import create_tracked_todo, subscribe_todo_to_trigger
from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.config.oauth_config import get_integration_by_id
from app.config.rate_limits import RateLimitPeriod, get_limits_for_plan
from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX
from app.constants.todos import (
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    INBOX_DESK_TITLE,
    PROVISION_INBOX_DESK_TASK,
    TodoActivityEvent,
)
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.models.message_models import MessageRequestWithHistory
from app.models.oauth_models import OAuthIntegration
from app.models.payment_models import PlanType
from app.services.chat import stream as chat_stream
from app.services.oauth.oauth_service import handle_oauth_connection
from app.services.platform_link_service import PlatformLinkService
from app.services.workflow.conversation_service import get_or_create_workflow_conversation
from app.services.workflow.playbook.record import CALL_ID_SEPARATOR
from app.utils.auth_utils import require_owner
from app.worker import TASK_FUNCTIONS
from app.workers.tasks.workflow_tasks import REPLAY_SUMMARY
from shared.py.wide_events import spawn_logged_task
from tests.e2e._harness.app_events import BotOutbox, gate_judge, signed_webhook_headers
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
    OpensReplyTask,
    OpensSubtasks,
    RepeatingTaskView,
    ReplaysPlaybook,
    Reports,
    RunOutcome,
    RunView,
    SavesPlaybook,
    Subtask,
    TaskNotFoundError,
    TaskView,
)
from tests.e2e._harness.transcript import Transcript
from tests.e2e._harness.turn_queue import APPROVAL_ID_FROM_PROMPT, TurnQueue
from tests.integration_account_factories import provider_account_id

TODOS = "/api/v1/todos"
WORKFLOWS = "/api/v1/workflows"
WEBHOOK = "/api/v1/webhook/composio"
WEBHOOK_MODULE = "app.api.v1.endpoints.webhook_composio"
#: Composio's event type for a new message in a Gmail inbox.
GMAIL_NEW_MESSAGE_EVENT = "gmail_new_gmail_message"
#: GAIA's id of the one account each connected app has in the journeys.
APP_ACCOUNT = "ca_1"
#: The job that hands an app event to the GAIA tasks watching it.
DISPATCH_TO_WATCHERS_JOB = "dispatch_todo_subscriptions"
#: The hour (UTC, the user's zone) app events arrive at in the journeys.
DAYTIME_HOUR = 10
#: How long after its armed time the worker picks a job up.
JOB_PICKUP_DELAY = timedelta(seconds=1)
#: The plan allowance every repeating task run is charged to.
RUN_LIMIT_FEATURE = "trigger_workflow_executions"
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
        skipped_events=tuple(
            skip["event"] for skip in (workflow.get("gate") or {}).get("recent_skips") or []
        ),
    )


async def _execute(job: JobDef, *, after: timedelta) -> str:
    """Run a job's function as the worker does, the clock moved to when it was armed for plus after."""
    due = datetime.fromtimestamp(job.score / 1000, UTC) + after
    with time_machine.travel(max(due, datetime.now(UTC)), tick=True):
        said = str(await _JOBS[job.function]({"job_id": job.job_id}, *job.args, **job.kwargs))
        # The run's delivery finishes in the background, still at that time.
        await drain_background_runs()
        return said


def _integration(integration_id: str) -> OAuthIntegration:
    integration = get_integration_by_id(integration_id)
    assert integration is not None, f"no app {integration_id}"
    return integration


def _next_daytime() -> datetime:
    """Return the next mid-morning on the user's (UTC) clock, outside every default quiet hour."""
    now = datetime.now(UTC)
    morning = now.replace(hour=DAYTIME_HOUR, minute=0, second=0, microsecond=0)
    return morning if morning > now else morning + timedelta(days=1)


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
        outbox: BotOutbox,
    ) -> None:
        self._outbox = outbox
        self._client = client
        self._user_id = user_id
        self._pool = pool
        self._executor = executor
        self._comms = comms
        self._last_fired: JobDef | None = None
        #: The results scripted for playbook replays' write-ups, in order.
        self._narrations: deque[str] = deque()
        self._unscripted_narrations: list[str] = []

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

    async def run_due(self, task_id: str, run: GaiaRun | None = None) -> str:
        """Let time pass to the task's next armed run and fire it, GAIA working as scripted.

        run is None for a firing the journey expects to stop before GAIA works.
        Returns what the worker said of the job, for a journey that checks it was skipped.
        """
        armed = await self._armed(task_id)
        assert armed, f"nothing is armed to run task {task_id}"
        if run is not None:
            await self._queue_run(task_id, run)
        with self._executor.provider_down() if isinstance(run, Breaks) else nullcontext():
            outcome = await self._run(armed[0])
        self._all_turns_taken()
        return outcome

    async def use_up_runs_for_the_day(self, task_id: str) -> None:
        """Spend the plan's GAIA runs for the day the task next runs on, as earlier runs would."""
        (job, *_) = await self._armed(task_id)
        with time_machine.travel(datetime.fromtimestamp(job.score / 1000, UTC)):
            limits = get_limits_for_plan(RUN_LIMIT_FEATURE, PlanType.PRO)
            day = RateLimitPeriod.DAY
            key = tiered_limiter._get_redis_key(self._user_id, RUN_LIMIT_FEATURE, day)
            await redis_cache.set(key, limits.day)

    async def runs_armed(self, task_id: str) -> int:
        """Count the runs waiting to fire for the task."""
        return len(await self._armed(task_id))

    async def woken_by_events(self, task_id: str) -> int:
        """Count the app events the task's history shows woke it."""
        events = await self._activity(task_id)
        return sum(event == TodoActivityEvent.TRIGGER_FIRED.value for event, _ in events)

    async def has_run_armed(self, task_id: str) -> bool:
        """Whether anything will run the task again."""
        return bool(await self._armed(task_id))

    def _all_turns_taken(self) -> None:
        """Fail unless GAIA was asked for exactly the turns the journey scripted."""
        for model in (self._executor, self._comms):
            assert not model.unscripted, f"GAIA took a turn nothing scripted: {model.unscripted}"
        assert self._executor.pending == 0, "GAIA was scripted for more work than it was asked for"
        assert self._comms.pending == 0, "a scripted reply or delivery was never asked for"
        assert not self._unscripted_narrations, (
            f"unscripted write-up: {self._unscripted_narrations}"
        )
        assert not self._narrations, "a replay was scripted, but the run never replayed"

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
            case OpensReplyTask(thread_id, title, report):
                self._executor.then(
                    [
                        call(
                            "create_tracked_todo",
                            {
                                "title": title,
                                "parent_todo_id": task_id,
                                "gmail_thread_id": thread_id,
                                "waiting_on": "time",
                                "scheduled_at": FIRST_LOOK,
                            },
                            call_id="tc_reply_task",
                        ),
                        report,
                    ]
                )
                tell(report)
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

    async def create_event_task(
        self, title: str, brief: str, *, app_event: str, only_when: str | None = None
    ) -> RepeatingTaskView:
        """Create a task GAIA runs whenever an app event arrives, optionally only when it matches."""
        payload: dict[str, Any] = {
            "title": title,
            "prompt": brief,
            "trigger_config": {"type": "integration", "trigger_name": app_event},
            "steps": [],
        }
        if only_when is not None:
            payload["runs_only_when"] = only_when
        return _repeating_view(_ok(await self._client.post(WORKFLOWS, json=payload)))

    async def pause(self, task_id: str) -> RepeatingTaskView:
        return _repeating_view(_ok(await self._client.post(f"{WORKFLOWS}/{task_id}/deactivate")))

    async def resume(self, task_id: str) -> RepeatingTaskView:
        return _repeating_view(_ok(await self._client.post(f"{WORKFLOWS}/{task_id}/activate")))

    # Apps and their events.

    async def watch_emails_from(self, task_id: str, sender: str) -> None:
        """Have the GAIA task wake whenever an email from sender arrives, as its watch tool sets."""
        said = await subscribe_todo_to_trigger.ainvoke(
            {
                "todo_id": task_id,
                "trigger_name": "gmail_new_message",
                "action": "execute",
                "conditions": [{"field_name": "sender", "operator": "contains", "value": sender}],
                "cooldown_seconds": 0,
            },
            config={"configurable": {"user_id": self._user_id}},
        )
        assert "is now watching" in said, said

    async def connect_app(self, integration_id: str) -> None:
        """Finish an app's OAuth connect, with every side effect the callback runs."""
        background = BackgroundTasks()
        await handle_oauth_connection(
            self._user_id,
            _integration(integration_id),
            background,
            connected_account_id=provider_account_id(APP_ACCOUNT),
        )
        await background()
        await drain_background_runs()
        # The worker picks up the set-up jobs the connect queued.
        for job in await self._pool.queued_jobs():
            if job.function == PROVISION_INBOX_DESK_TASK:
                await self._run(job)

    async def inbox_desk(self) -> TaskView | None:
        """Return the Inbox desk GAIA keeps for the user, None when there is none."""
        desks = [t for t in await self._gaia_tasks() if t.title == INBOX_DESK_TITLE]
        assert len(desks) <= 1, f"more than one Inbox desk: {desks}"
        return desks[0] if desks else None

    async def app_disconnects(self, integration_id: str) -> None:
        """Deliver the provider's notice that the app's account expired."""
        toolkit = _integration(integration_id).composio_config
        assert toolkit is not None, f"{integration_id} is not a Composio app"
        await self._webhook(
            {
                "id": f"msg_{uuid4().hex[:8]}",
                "type": "composio.connected_account.expired",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "id": provider_account_id(APP_ACCOUNT),
                    "user_id": self._user_id,
                    "status": "EXPIRED",
                    "status_reason": "refresh_token_revoked",
                    "is_disabled": False,
                    "toolkit": {"slug": toolkit.toolkit.upper()},
                    "auth_config": {"id": toolkit.auth_config_id, "auth_scheme": "OAUTH2"},
                    "state": {"authScheme": "OAUTH2", "val": {"status": "EXPIRED"}},
                    "data": {},
                    "params": {},
                },
            }
        )

    async def new_email(
        self, *, subject: str, sender: str, gate_passes: bool | None = None, delivery_id: str
    ) -> None:
        """Deliver a new-email event for the user's inbox; gate_passes is what the matcher judges."""
        message_id = f"msg-{delivery_id}"
        data = {
            "connection_id": provider_account_id(APP_ACCOUNT),
            "connection_nano_id": "nano-1",
            "trigger_nano_id": "ti_nano",
            "trigger_id": "ti-gmail",
            "user_id": self._user_id,
            "message_id": message_id,
            "thread_id": f"thread-{delivery_id}",
            "subject": subject,
            "sender": sender,
            "message_text": f"{subject} from {sender}",
            "payload": {"message_id": message_id},
        }
        verdict = 0.5 if gate_passes is None else (0.05 if gate_passes else 0.99)
        with gate_judge(not_needed=verdict), time_machine.travel(_next_daytime(), tick=True):
            await self._webhook(
                {
                    "type": GMAIL_NEW_MESSAGE_EVENT,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": data,
                },
                webhook_id=f"wh-{delivery_id}",
            )

    async def _webhook(self, body: dict[str, Any], *, webhook_id: str | None = None) -> None:
        spawned: list[asyncio.Task[object]] = []

        def recording_spawn(operation: str, coro: Any, **ctx: Any) -> asyncio.Task[object]:
            task = spawn_logged_task(operation, coro, **ctx)
            spawned.append(task)
            return task

        raw = json.dumps(body).encode()
        with patch(f"{WEBHOOK_MODULE}.spawn_logged_task", side_effect=recording_spawn):
            response = await self._client.post(
                WEBHOOK,
                content=raw,
                headers=signed_webhook_headers(raw, webhook_id or f"wh-{uuid4().hex}"),
            )
            assert response.status_code == 200, response.text
            await asyncio.gather(*spawned)
        await drain_background_runs()
        # The worker hands the event to the tasks watching it at once.
        for job in await self._pool.queued_jobs():
            if job.function == DISPATCH_TO_WATCHERS_JOB:
                await self._run(job)

    async def repeating_tasks(self) -> list[RepeatingTaskView]:
        """Return the tasks GAIA repeats, as their list shows them."""
        body = _ok(await self._client.get(WORKFLOWS))
        return [_repeating_view({"workflow": w}) for w in body["workflows"]]

    async def brief_of(self, task_id: str) -> str:
        return _ok(await self._client.get(f"{WORKFLOWS}/{task_id}"))["workflow"]["prompt"]

    async def reset_to_default(self, task_id: str) -> None:
        """Put a task GAIA set up for an app back the way it shipped."""
        _ok(await self._client.post(f"{WORKFLOWS}/{task_id}/reset-to-default"))

    async def publish(self, task_id: str) -> str:
        """Publish the task as a template anyone can see; return its public reference."""
        return _ok(await self._client.post(f"{WORKFLOWS}/{task_id}/publish"))["slug"]

    async def unpublish(self, task_id: str) -> None:
        _ok(await self._client.post(f"{WORKFLOWS}/{task_id}/unpublish"))

    async def public_template(self, ref: str) -> str | None:
        """Return the title a visitor sees at a template's public link, None when it is not there."""
        response = await self._client.get(f"{WORKFLOWS}/public/{ref}")
        if response.status_code == 404:
            return None
        return _ok(response)["workflow"]["title"]

    async def community_templates(self) -> list[str]:
        """Return the titles the community page lists."""
        body = _ok(await self._client.get(f"{WORKFLOWS}/community", params={"limit": 50}))
        return [card["title"] for card in body["workflows"]]

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
        hand_off = [call("call_executor", {"task": f"run {task_id}"}, call_id="tc_run"), ON_IT]
        match run:
            case Reports(report):
                self._comms.then(hand_off)
                self._executor.then([_DECLINE_PLAYBOOK, report])
            case SavesPlaybook(report):
                self._comms.then(hand_off)
                self._executor.then(
                    [
                        call(
                            "retrieve_tools",
                            {"exact_tool_names": [GATED_ACTION]},
                            call_id="tc_find",
                        ),
                        call(GATED_ACTION, GATED_ACTION_ARGS, call_id="tc_work"),
                        call(
                            "write_playbook",
                            {
                                "description": "Draw the plan's flowchart.",
                                "steps": [{"call": f"{GATED_ACTION}{CALL_ID_SEPARATOR}1"}],
                                "result_brief": "Say the flowchart is drawn.",
                            },
                            call_id="tc_playbook",
                        ),
                        report,
                    ]
                )
            case ReplaysPlaybook(report):
                self._narrations.append(report)
            case _:
                raise NotImplementedError(f"a repeating task cannot be scripted to {run}")
        # The run's write-up is asked for whether or not it is then delivered.
        if not isinstance(run, ReplaysPlaybook):
            self._comms.then([report])

    async def narrate_replay(self, schema: type[BaseModel], prompt: str, **_: object) -> BaseModel:
        """Answer a playbook replay's write-up call with the journey's scripted result."""
        if not self._narrations:
            self._unscripted_narrations.append(prompt[-300:])
            raise AssertionError("a replay was written up with no result scripted")
        return schema.model_validate({"result": self._narrations.popleft()})

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
                RunView(
                    outcome=_WORKFLOW_RUN_STATUS[e["status"]],
                    reason=e.get("summary"),
                    replayed=e.get("summary") == REPLAY_SUMMARY,
                )
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

    def messaged_on_chat_apps(self) -> list[Delivered]:
        """Return every message GAIA sent the user on a linked chat app, oldest first."""
        return [
            Delivered(title="", body=text, channel=platform) for platform, text in self._outbox.sent
        ]

    async def link_chat_app(self, platform: str) -> None:
        """Link the user's account on a chat app (Telegram, Discord, Slack), as its link flow does."""
        await PlatformLinkService.link_account(self._user_id, platform, f"{platform}-user-1001")

    async def chat(self, task_id: str) -> list[ChatLine]:
        """Return the task's own chat as the user opens it from the task, oldest first."""
        if _is_workflow(task_id):
            workflow = (await self.get_repeating(task_id)).title
            conversation_id = await get_or_create_workflow_conversation(
                workflow_id=task_id, user_id=self._user_id, workflow_title=workflow
            )
        else:
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
