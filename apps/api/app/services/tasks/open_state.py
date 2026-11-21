"""The open-state rule: every open one-off GAIA task has a next step that code acts on.

An open GAIA task that does not repeat and is not paused always says what it waits on
(waiting.on) and has a future next_check_at within that state's limit. Writes that would
break it are refused with the problems spelled out for the model; the engine repairs a
run that ends without one.
"""

from datetime import datetime, timedelta

from app.constants.tasks import Assignee, WhenKind
from app.constants.todos import (
    MAX_HOLD_CHECK_AHEAD,
    MAX_HOLD_CHECKS,
    MAX_NEXT_CHECK_AHEAD,
    MAX_QUESTION_EXPIRY,
    MAX_REASKS,
    NoReplyPlan,
    WaitingOn,
    WakeReason,
)
from app.models.task_models import TaskDocument, TaskUpdate, Waiting, WaitingQuestion

# A duration resolved at parse time lands a moment under its limit by validation time.
_LIMIT_SLACK = timedelta(minutes=5)

WAITING_ON_CHOICES = (
    "'time' (nothing outside to wait for, just look again then), "
    "'event' (a watch or thread will wake it; next_check is the backup check), "
    "'user' (you asked them something; next_check is when the question expires; a "
    "task of theirs you keep after until they confirm is not a question: it gets a "
    "repeat or a next check, never a plan that ends it unanswered), "
    "'sub_todos' (its subtasks are doing the work; next_check is the backup check), "
    "'unplanned' (captured with no plan yet; next_check is when to plan it)"
)
NEXT_CHECK_HINT = (
    "Pick it by urgency: hours ('4h') when urgent, days ('3d') for normal work, "
    "up to '2w' for a loose idea."
)
_PLAN_WORDS = {
    NoReplyPlan.ASK_AGAIN: "ask once more",
    NoReplyPlan.HOLD: "hold until they answer",
}


def keeps_open_state(task: TaskDocument) -> bool:
    """Whether the open-state rule binds this task: open, GAIA's, one-off and on."""
    return (
        task.assignee is Assignee.GAIA
        and not task.completed
        and task.pause_reason is None
        and task.when.kind is not WhenKind.REPEAT
    )


def waiting_after(
    current: Waiting | None,
    *,
    on: WaitingOn,
    question: str | None,
    if_no_reply: NoReplyPlan | None,
    default_action: str | None,
) -> Waiting:
    """Build what the task waits on once a write lands; a new question starts its holds at zero."""
    if on is not WaitingOn.USER or question is None:
        return Waiting(on=on)
    asked = current.question if current is not None else None
    holds = asked.hold_checks if asked is not None and asked.text == question else 0
    return Waiting(
        on=on,
        question=WaitingQuestion(
            text=question,
            if_no_reply=if_no_reply,
            default_action=default_action,
            hold_checks=holds,
        ),
    )


def next_check_limit(task: TaskDocument) -> timedelta:
    """How far out this task's next check may be set."""
    waiting = task.waiting
    if waiting is None or waiting.on is not WaitingOn.USER:
        return MAX_NEXT_CHECK_AHEAD
    asked = waiting.question
    if asked is not None and asked.if_no_reply is NoReplyPlan.HOLD and asked.hold_checks:
        return MAX_HOLD_CHECK_AHEAD
    return MAX_QUESTION_EXPIRY


def open_state_problems(task: TaskDocument, now: datetime) -> list[str]:
    """Everything that keeps this task from having a valid next step; empty when it has one."""
    if not keeps_open_state(task):
        return []
    problems: list[str] = []
    if task.waiting is None:
        problems.append(
            f"waiting_on is missing: say what this task waits for: {WAITING_ON_CHOICES}."
        )
    problems.extend(_next_check_problems(task, now))
    if task.waiting is not None and task.waiting.on is WaitingOn.USER:
        problems.extend(_question_problems(task))
    return problems


def _next_check_problems(task: TaskDocument, now: datetime) -> list[str]:
    if task.next_check_at is None:
        return [
            "next_check is missing: set when GAIA next looks at this task, as an ISO "
            f"datetime or a duration from now. {NEXT_CHECK_HINT}"
        ]
    if task.next_check_at <= now:
        return ["next_check is in the past: set a future next check."]
    limit = next_check_limit(task)
    if task.next_check_at - now > limit + _LIMIT_SLACK:
        waiting = task.waiting.on.value if task.waiting else "this state"
        return [
            f"next_check is {(task.next_check_at - now).days} days out; with waiting_on="
            f"'{waiting}' the next check is at most {limit.days} days away. A longer wait is "
            "fine: look again by then and set the next check from there."
        ]
    return []


def _question_problems(task: TaskDocument) -> list[str]:
    asked = task.waiting.question if task.waiting else None
    if asked is None:
        return ["waiting_on='user' needs question: the exact question you asked them."]
    if asked.if_no_reply is None:
        return [
            "waiting_on='user' needs if_no_reply: decide now, while you know why you asked, "
            "what happens if they never answer: 'ask_again' (it matters: ask once more), "
            "'proceed' (carry out default_action), 'hold' (nothing can move without the answer)."
        ]
    if asked.if_no_reply is NoReplyPlan.PROCEED and not asked.default_action:
        return [
            "if_no_reply='proceed' needs default_action: what you will do if they never answer."
        ]
    if asked.if_no_reply is NoReplyPlan.ASK_AGAIN and task.reasks_used >= MAX_REASKS:
        return [
            "if_no_reply='ask_again' is not available: this task already used its one re-ask. "
            "Pick 'proceed' with a default_action, or 'hold'."
        ]
    return []


def wake_budget_update(task: TaskDocument) -> TaskUpdate | None:
    """Return the counter a question's expiry spends, written before the run that carries it out."""
    waiting = task.waiting
    if task.when.kind is WhenKind.REPEAT or waiting is None or waiting.question is None:
        return None
    asked = waiting.question
    if asked.if_no_reply is NoReplyPlan.ASK_AGAIN:
        return TaskUpdate(reasks_used=task.reasks_used + 1)
    if asked.if_no_reply is NoReplyPlan.HOLD:
        held = asked.model_copy(update={"hold_checks": asked.hold_checks + 1})
        return TaskUpdate(waiting=waiting.model_copy(update={"question": held}))
    return None


def wake_reason(task: TaskDocument) -> WakeReason:
    """Why a scheduled run of this one-off task woke, once its budget was spent."""
    match task.waiting.on if task.waiting else None:
        case WaitingOn.USER:
            return _question_wake(task)
        case WaitingOn.EVENT:
            return WakeReason.BACKUP_CHECK
        case WaitingOn.SUB_TODOS:
            return WakeReason.SUB_TODO_CHECK
        case WaitingOn.UNPLANNED:
            return WakeReason.PLAN_IT
    return WakeReason.SCHEDULED_CHECK


def hold_ran_out(task: TaskDocument) -> bool:
    """Return whether an unanswered hold has had all its reminders, so its next wake closes the task."""
    asked = task.waiting.question if task.waiting else None
    return (
        asked is not None
        and asked.if_no_reply is NoReplyPlan.HOLD
        and asked.hold_checks > MAX_HOLD_CHECKS
    )


def _question_wake(task: TaskDocument) -> WakeReason:
    asked = task.waiting.question if task.waiting else None
    if asked is None or asked.if_no_reply is None:
        return WakeReason.QUESTION_EXPIRED
    match asked.if_no_reply:
        case NoReplyPlan.ASK_AGAIN:
            return WakeReason.REASK_DUE
        case NoReplyPlan.PROCEED:
            return WakeReason.DEFAULT_DUE
        case NoReplyPlan.HOLD:
            return WakeReason.HOLD_LAST_CHECK if hold_ran_out(task) else WakeReason.HOLD_CHECK


def _relative(at: datetime, now: datetime) -> str:
    delta = at - now
    if delta <= timedelta(0):
        return "due now"
    if delta < timedelta(hours=1):
        return f"in {max(1, delta // timedelta(minutes=1))}m"
    if delta < timedelta(days=1):
        return f"in {delta // timedelta(hours=1)}h"
    return f"in {delta.days}d"


def no_reply_plan_words(task: TaskDocument) -> str:
    """Say what the task does when its question expires."""
    asked = task.waiting.question if task.waiting else None
    if asked is None or asked.if_no_reply is None:
        return "nothing decided"
    if asked.if_no_reply is NoReplyPlan.PROCEED:
        return f"proceed: {asked.default_action}"
    return _PLAN_WORDS[asked.if_no_reply]


def describe_open_state(task: TaskDocument, now: datetime) -> str:
    """One phrase saying what the task waits on and when it next acts."""
    if task.pause_reason is not None:
        return "paused by the system"
    if task.when.kind is WhenKind.REPEAT:
        next_run = task.when.next_run
        return f"repeats {task.when.rule}, next run {_relative(next_run, now) if next_run else 'never'}"
    when = _relative(task.next_check_at, now) if task.next_check_at else "never"
    if task.waiting is None:
        return f"no next step set (next run {when})"
    match task.waiting.on:
        case WaitingOn.TIME:
            return f"next check {when}"
        case WaitingOn.EVENT:
            return f"waiting on an event, backup check {when}"
        case WaitingOn.USER:
            asked = task.waiting.question
            return (
                f'waiting on the user: "{asked.text if asked else ""}" (expires {when}, '
                f"then {no_reply_plan_words(task)})"
            )
        case WaitingOn.SUB_TODOS:
            return f"waiting on its subtasks, backup check {when}"
        case WaitingOn.UNPLANNED:
            return f"not planned yet, plan it {when}"
