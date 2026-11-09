"""Turn-start context for comms: the work running beside the chat.

A background executor run and a browser task both outlive the turn that started
them. Comms is told, once at the start of each turn it answers, what each is doing
now: the facts are written into the thread with that turn, so the request stays
append-only and every later turn keeps them as history.
"""

from app.agents.context.section_context import SectionContext
from app.agents.core.background.executor_progress import describe_progress, read_progress
from app.agents.core.background.executor_queue import read_executor_activity
from app.agents.core.background.running_registry import RunningSubagents
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.models.executor_activity_models import ExecutorActivity
from app.services.browser.chat_task import ChatBrowserTasks, ChatTurn, chat_browser_tasks
from shared.py.wide_events import log


def executor_status_text(activity: ExecutorActivity, task_id: str, running: bool) -> str:
    """Say whether background work is running, and what became of the last task when it is not."""
    task = f"task_id: {task_id or 'unknown'}"
    if running:
        return f"Background work is running right now ({task}). Its result has not arrived yet."
    if activity is ExecutorActivity.DEAD:
        return (
            f"No background work is running. The last task ({task}) stopped before it "
            "finished, and its result will not arrive."
        )
    return (
        "No background work is running right now. Every earlier hand-off in this chat has "
        "finished or stopped, even one whose result you have not seen."
    )


async def build_executor_status_block(ctx: SectionContext) -> str:
    """Return the conversation's background-work status, read from the busy lock and the subagent registry."""
    if not ctx.conversation_id:
        return ""
    try:
        snapshot = await read_executor_activity(ctx.conversation_id)
        subagents = await RunningSubagents(ctx.conversation_id).live()
        running = snapshot.activity is ExecutorActivity.RUNNING or bool(subagents)
        text = executor_status_text(snapshot.activity, snapshot.task_id, running)
        if snapshot.activity is ExecutorActivity.RUNNING:
            progress = describe_progress(await read_progress(ctx.conversation_id, snapshot.holder))
            if progress:
                text = f"{text} What it has done so far:\n{progress}"
        return text
    except Exception as e:
        log.error(f"{LogTag.AGENT} Executor status unavailable", error_type=type(e).__name__)
        return ""


def describe_browser_tasks(tasks: ChatBrowserTasks) -> str:
    """Write each task's facts: whether it runs or waits on the user, and for what."""
    lines: list[str] = []
    for job in tasks.running:
        paused = tasks.paused
        if paused is not None and paused.job_id == job.job_id:
            lines.append(
                "Paused, waiting for the user to finish a step in the live view: "
                f"{paused.reason}. Task: {job.task}"
            )
        else:
            lines.append(f"Running. Task: {job.task}")
    return "\n".join(lines)


async def build_browser_task_block(ctx: SectionContext) -> str:
    """Return a <browser_task> block while a browser task this chat controls has not ended.

    Only a turn answering the user's own message gets one: the user answers a
    task in chat ("done", "stop"), and a background run has nobody typing.
    """
    if ctx.execution_mode == "background" or not ctx.conversation_id or not ctx.user_id:
        return ""
    turn = ChatTurn(
        conversation_id=ctx.conversation_id,
        user_id=ctx.user_id,
        source=ConversationSource.coerce(ctx.source),
    )
    try:
        tasks = await chat_browser_tasks(turn)
    except Exception as e:
        log.error(
            f"{LogTag.BROWSER} Browser task status unavailable", error_type=type(e).__name__
        )
        return ""
    if not tasks.running:
        return ""
    return wrap_agent_payload(AgentTag.BROWSER_TASK, describe_browser_tasks(tasks))
