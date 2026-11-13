"""Comms' work tools when it has no direct executor: every piece of work is a tracked task.

A task is a tracked todo whose run is the executor. start_task creates it and arms its run,
message_task steers it, cancel_task stops it and find_tasks finds it across every conversation.
Its result reaches the user through the outbox as the todo run's report; read_task (in
work_record_tool) answers follow-ups from its record.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.confirmation_gate import spend_confirmation
from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_queue import read_executor_activity
from app.agents.core.background.session import mark_task_handed_off
from app.agents.core.subagents.subagent_runner import compose_executor_brief
from app.agents.tools.executor_tool import handoff_message, stop_executor_work
from app.agents.tools.tracked_todo_formatting import format_canvas_match
from app.constants.agents import TimeHorizon
from app.constants.tasks import (
    HIDDEN_TASK_LABEL,
    TASK_CONTEXT_LIST_MAX,
    TASK_FIND_RESULTS,
    TASK_START_DELAY,
)
from app.constants.todos import CANVAS_CONTEXT_SECTION, WaitingOn
from app.db.repositories.todos import todo_repository
from app.models.agent_models import agent_configurable, get_user_id, read_agent_configurable
from app.models.executor_activity_models import ExecutorActivity
from app.models.ownership_models import ExecutorIntent
from app.models.todo_models import AskOrigin, TodoDocument, TodoUpdate, TodoUpdateRequest
from app.services.analytics_service import capture
from app.services.canvas_markdown import with_section_appended
from app.services.conversation_service import get_or_create_todo_conversation
from app.services.todo_activity import TodoActivityEvent, record_activity
from app.services.todos.todo_service import TodoService
from app.services.tracked_todo_service import CANVAS_TEMPLATE, tracked_todo_service
from app.utils.canvas_vector_utils import search_canvas_context
from app.utils.timezone import home_timezone_from_config
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import (
    TaskCancelled,
    TaskFound,
    TaskMessaged,
    TaskStarted,
)

NO_SUCH_TASK = "You have no task with that id. Find it with find_tasks."


async def _owned_task(config: RunnableConfig, task_id: str) -> TodoDocument | None:
    return await todo_repository.get(task_id, user_id=get_user_id(config))


def _ask_origin(config: RunnableConfig) -> AskOrigin:
    """The turn asking now: the conversation its answer returns to, the message it settles, the user's own words."""
    configurable = read_agent_configurable(config)
    return AskOrigin(
        conversation_id=configurable.thread_id or "",
        message_id=agent_configurable(config).get("bot_message_id"),
        user_request=configurable.user_request,
    )


def _in_another_conversation(task: TodoDocument, config: RunnableConfig) -> bool:
    return task.source_conversation_id != read_agent_configurable(config).thread_id


async def _arm_run(task: TodoDocument) -> None:
    """Make the task's next run start now: reopened if finished, armed one beat ahead, queued without delay."""
    now = datetime.now(UTC)
    if task.completed:
        await TodoService.update_todo(task.id, TodoUpdateRequest(completed=False), task.user_id)
    first_fire = now + TASK_START_DELAY
    await todo_repository.update(
        task.id,
        user_id=task.user_id,
        update=TodoUpdate(scheduled_at=first_fire, waiting_on=WaitingOn.TIME, gaia_retry_count=0),
    )
    await tracked_todo_service.schedule_execution(task.id, first_fire, defer_until=now)


@tool
async def start_task(
    config: RunnableConfig,
    title: Annotated[str, "Short name of the task, in the user's words (max 200 characters)."],
    request: Annotated[
        str,
        "Everything the executor needs: what to do, with every detail from the user and the "
        "thread, so the task stands alone.",
    ],
    acceptance_criteria: Annotated[
        list[str],
        "What must be TRUE for this task to count as done, as a checklist. NEVER omit: even a "
        "single-step ask needs a concrete done state.",
    ],
    desired_outcome: Annotated[
        str,
        "What the user actually wants in the end, in one line, beyond the literal ask.",
    ],
    time_horizon: Annotated[
        TimeHorizon,
        "one_shot (done in this run), deadline (must happen by a date) or ongoing (needs attention "
        "over days). Deadline and ongoing work leave a follow-up that wakes on its own.",
    ],
    defaults_assumed: Annotated[
        list[str] | None,
        "Every safe default you picked for a missing detail, so the result names it. Omit when none.",
    ] = None,
    irreversible_approved: Annotated[
        bool,
        "True only when the user's own message already said yes to the exact delete, bulk change, "
        "send or post this task performs. False makes the executor prepare it and ask.",
    ] = False,
    start_at: Annotated[
        datetime | None,
        "When the user asked it to start later ('tomorrow at 9', 'Friday'): the time as an ISO "
        "datetime, with their offset when they named a timezone and without it for their own "
        "clock. Omit to start now. For 'when X happens', start now and say the condition in "
        "request: the task sets its own watch.",
    ] = None,
    visible: Annotated[
        bool,
        "True for ongoing or scheduled work the user will want in their todo list; false for a "
        "one-off ask, which stays out of their list but is still found by find_tasks.",
    ] = False,
) -> str:
    """Start work as a tracked task; the only way to get anything done that needs a tool.

    Anything that needs a tool is a task: reading their inbox or calendar, sending, creating,
    changing, searching their accounts, a reminder, a connection. Pure conversation is not.
    The task runs on its own and its result reaches the user by itself.
    """
    user_id = get_user_id(config)
    configurable = read_agent_configurable(config)
    conversation_id = configurable.thread_id or ""
    now = datetime.now(UTC)
    if start_at is not None and start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=home_timezone_from_config(config).tzinfo)
    first_fire = start_at if start_at is not None else now + TASK_START_DELAY
    if first_fire <= now:
        return "start_at is in the past. Give the instant it should start, or omit it to start now."

    answers_gaias_question = await spend_confirmation(conversation_id)
    brief = compose_executor_brief(
        request,
        acceptance_criteria,
        verbatim_request=configurable.user_request,
        intent=ExecutorIntent(
            desired_outcome=desired_outcome,
            time_horizon=time_horizon,
            defaults_assumed=tuple(defaults_assumed or ()),
            irreversible_approved=irreversible_approved and answers_gaias_question,
        ),
    )
    open_tasks = await todo_repository.list_active_tracked(
        user_id, limit=TASK_CONTEXT_LIST_MAX, top_level=True
    )
    created = await tracked_todo_service.create_tracked_todo(
        user_id=user_id,
        title=title,
        description=desired_outcome,
        initial_canvas=with_section_appended(
            CANVAS_TEMPLATE.format(title=title), CANVAS_CONTEXT_SECTION, brief
        ),
        labels=None if visible else [HIDDEN_TASK_LABEL],
        source_conversation_id=conversation_id,
        ask_origin=_ask_origin(config),
        schedule=TodoUpdate(scheduled_at=first_fire, waiting_on=WaitingOn.TIME),
        done_when=acceptance_criteria,
    )
    await tracked_todo_service.schedule_execution(
        created.todo.id, first_fire, defer_until=first_fire if start_at else now
    )
    stream_id = agent_configurable(config).get("stream_id")
    if stream_id:
        mark_task_handed_off(stream_id)
    capture(
        UserId(user_id),
        TaskStarted(
            timing="scheduled" if start_at else "now", visible=visible, open_tasks=len(open_tasks)
        ),
    )
    return handoff_message(created.todo.id)


@tool
async def message_task(
    config: RunnableConfig,
    task_id: Annotated[str, "The task to steer, from start_task, find_tasks or the open tasks."],
    text: Annotated[
        str,
        "What the user said about it ('also cc Jonah', 'make it Friday', 'check the price again'), "
        "with every detail.",
    ],
) -> str:
    """Steer a task, running or finished: it picks the message up and carries on.

    A running task takes it into the run in flight; a finished one runs again with it. Use it for
    anything that changes or extends a task, and for a re-check when its report is too old
    to state as current.
    """
    task = await _owned_task(config, task_id)
    if task is None:
        return NO_SUCH_TASK
    chat_id = await get_or_create_todo_conversation(task.user_id, task.id, task.title)
    running = (await read_executor_activity(chat_id)).activity is ExecutorActivity.RUNNING
    await todo_repository.update(
        task.id, user_id=task.user_id, update=TodoUpdate(ask_origin=_ask_origin(config))
    )
    if running:
        await ExecutorInbox(chat_id).append(str(uuid4()), text)
    else:
        await record_activity(task.id, task.user_id, TodoActivityEvent.USER_MESSAGE, text)
        await _arm_run(task)
    capture(
        UserId(task.user_id),
        TaskMessaged(running=running, cross_conversation=_in_another_conversation(task, config)),
    )
    return (
        "Passed to the run in progress; its result reaches the user by itself."
        if running
        else "Running again with it; its result reaches the user by itself."
    )


@tool
async def cancel_task(
    config: RunnableConfig,
    task_id: Annotated[str, "The task to stop."],
) -> str:
    """Stop a task, only when the user explicitly asks to stop, cancel or abort it.

    A running task is cancelled and an open one is closed; neither runs again.
    """
    task = await _owned_task(config, task_id)
    if task is None:
        return NO_SUCH_TASK
    if task.completed:
        return "That task has already finished; there is nothing to stop."
    chat_id = await get_or_create_todo_conversation(task.user_id, task.id, task.title)
    was_running = (await read_executor_activity(chat_id)).activity is ExecutorActivity.RUNNING
    await stop_executor_work(
        {**agent_configurable(config), "thread_id": chat_id}, chat_id, [], None
    )
    await tracked_todo_service.complete_tracked_todo(task.id, task.user_id, "Stopped by the user.")
    capture(UserId(task.user_id), TaskCancelled(was_running=was_running))
    return "Stopped." if was_running else "Closed; it will not run."


@tool
async def find_tasks(
    config: RunnableConfig,
    query: Annotated[
        str, "What the task was about: the ask, a person, a date, a result. Any conversation."
    ],
) -> str:
    """Find the user's tasks by what they were about, across every conversation, open or finished.

    Returns each match with its id, for read_task and message_task. Use it when they refer to
    something done or started somewhere else, or when the open tasks listed do not include it.
    """
    user_id = get_user_id(config)
    matches = await search_canvas_context(
        query=query, user_id=user_id, top_k=TASK_FIND_RESULTS, include_completed=True
    )
    owned = {
        task.id: task
        for task in await todo_repository.find_by_ids(user_id, [m["todo_id"] for m in matches])
    }
    capture(
        UserId(user_id),
        TaskFound(
            results=len(matches),
            cross_conversation=sum(
                _in_another_conversation(owned[m["todo_id"]], config)
                for m in matches
                if m["todo_id"] in owned
            ),
        ),
    )
    if not matches:
        return "No task matches that."
    return "\n".join(format_canvas_match(match) for match in matches)


tools = [start_task, message_task, cancel_task, find_tasks]
