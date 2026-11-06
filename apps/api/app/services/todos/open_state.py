"""The open-state rule: every open tracked todo has a next step that code acts on.

A tracked todo that is open, not recurring and not paused always says what it is
waiting on (waiting_on) and has a future scheduled_at within that state's limit.
Writes that would break it are refused with the problems spelled out for the
model; the worker repairs a run that ends without one.
"""

from datetime import datetime, timedelta

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
from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.todos.errors import OpenStateError

# A duration resolved at parse time lands a moment under its limit by validation time.
_LIMIT_SLACK = timedelta(minutes=5)

WAITING_ON_CHOICES = (
    "'time' (nothing outside to wait for, just look again then), "
    "'event' (a watch or thread will wake it; scheduled_at is the backup check), "
    "'user' (you asked them something; scheduled_at is when the question expires; a "
    "task of theirs you keep after until they confirm is not a question: it gets a "
    "recurrence or a next check, never a plan that ends it unanswered), "
    "'sub_todos' (its sub-todos are doing the work; scheduled_at is the backup check), "
    "'unplanned' (captured with no plan yet; scheduled_at is when to plan it)"
)
NEXT_CHECK_HINT = (
    "Pick it by urgency: hours ('4h') when urgent, days ('3d') for normal work, "
    "up to '2w' for a loose idea."
)
_PLAN_WORDS = {
    NoReplyPlan.ASK_AGAIN: "ask once more",
    NoReplyPlan.HOLD: "hold until they answer",
}


#: The fields that decide a todo's next step; an update touching none cannot change it.
OPEN_STATE_FIELDS = frozenset(
    {
        "scheduled_at",
        "recurrence",
        "waiting_on",
        "question",
        "if_no_reply",
        "default_action",
        "pause_reason",
    }
)


def touches_open_state(update: TodoUpdate) -> bool:
    """Return whether this update sets any field that decides the todo's next step."""
    return bool(update.model_fields_set & OPEN_STATE_FIELDS)


def state_after(existing: TodoDocument, update: TodoUpdate) -> TodoDocument:
    """Return the todo as it would be once this update is written."""
    return existing.model_copy(update=update.model_dump(exclude_unset=True))


def with_waiting_normalized(existing: TodoDocument | None, update: TodoUpdate) -> TodoUpdate:
    """Clear the question fields when the todo stops waiting on the user; a new question resets holds."""
    fields = update.model_fields_set
    extra: dict[str, object] = {}
    if "waiting_on" in fields and update.waiting_on is not WaitingOn.USER:
        extra = {"question": None, "if_no_reply": None, "default_action": None, "hold_checks": 0}
    elif "question" in fields and (existing is None or existing.question != update.question):
        extra = {"hold_checks": 0}
    if not extra:
        return update
    return TodoUpdate.model_validate({**update.model_dump(exclude_unset=True), **extra})


def next_check_limit(doc: TodoDocument) -> timedelta:
    """How far out this todo's next check may be set."""
    if doc.waiting_on is not WaitingOn.USER:
        return MAX_NEXT_CHECK_AHEAD
    if doc.if_no_reply is NoReplyPlan.HOLD and doc.hold_checks:
        return MAX_HOLD_CHECK_AHEAD
    return MAX_QUESTION_EXPIRY


def open_state_problems(doc: TodoDocument, now: datetime) -> list[str]:
    """Everything that keeps this todo from having a valid next step; empty when it has one."""
    if doc.completed or doc.pause_reason is not None:
        return []
    if doc.recurrence:
        if doc.scheduled_at:
            return []
        return ["recurrence needs scheduled_at: either clear recurrence or provide scheduled_at."]
    problems: list[str] = []
    if doc.waiting_on is None:
        problems.append(
            f"waiting_on is missing: say what this todo waits for: {WAITING_ON_CHOICES}."
        )
    problems.extend(_next_check_problems(doc, now))
    if doc.waiting_on is WaitingOn.USER:
        problems.extend(_question_problems(doc))
    return problems


def _next_check_problems(doc: TodoDocument, now: datetime) -> list[str]:
    if doc.scheduled_at is None:
        return [
            "scheduled_at is missing: set when GAIA next looks at this todo, as an ISO "
            f"datetime or a duration from now. {NEXT_CHECK_HINT}"
        ]
    if doc.scheduled_at <= now:
        return ["scheduled_at is in the past: set a future next check."]
    limit = next_check_limit(doc)
    if doc.scheduled_at - now > limit + _LIMIT_SLACK:
        waiting = doc.waiting_on.value if doc.waiting_on else "this state"
        return [
            f"scheduled_at is {(doc.scheduled_at - now).days} days out; with waiting_on="
            f"'{waiting}' the next check is at most {limit.days} days away. A longer wait is "
            "fine: look again by then and set the next check from there."
        ]
    return []


def _question_problems(doc: TodoDocument) -> list[str]:
    problems: list[str] = []
    if not doc.question:
        problems.append("waiting_on='user' needs question: the exact question you asked them.")
    if doc.if_no_reply is None:
        problems.append(
            "waiting_on='user' needs if_no_reply: decide now, while you know why you asked, "
            "what happens if they never answer: 'ask_again' (it matters: ask once more), "
            "'proceed' (carry out default_action), 'hold' (nothing can move without the answer)."
        )
    elif doc.if_no_reply is NoReplyPlan.PROCEED and not doc.default_action:
        problems.append(
            "if_no_reply='proceed' needs default_action: what you will do if they never answer."
        )
    elif doc.if_no_reply is NoReplyPlan.ASK_AGAIN and doc.reasks_used >= MAX_REASKS:
        problems.append(
            "if_no_reply='ask_again' is not available: this todo already used its one re-ask. "
            "Pick 'proceed' with a default_action, or 'hold'."
        )
    return problems


def wake_budget_update(doc: TodoDocument) -> TodoUpdate | None:
    """Return the counter a question's expiry spends, written before the run that carries it out."""
    if doc.recurrence or doc.waiting_on is not WaitingOn.USER:
        return None
    if doc.if_no_reply is NoReplyPlan.ASK_AGAIN:
        return TodoUpdate(reasks_used=doc.reasks_used + 1)
    if doc.if_no_reply is NoReplyPlan.HOLD:
        return TodoUpdate(hold_checks=doc.hold_checks + 1)
    return None


def wake_reason(doc: TodoDocument) -> WakeReason:
    """Why a scheduled run of this non-recurring todo woke, once its budget was spent."""
    match doc.waiting_on:
        case WaitingOn.USER:
            return _question_wake(doc)
        case WaitingOn.EVENT:
            return WakeReason.BACKUP_CHECK
        case WaitingOn.SUB_TODOS:
            return WakeReason.SUB_TODO_CHECK
        case WaitingOn.UNPLANNED:
            return WakeReason.PLAN_IT
    return WakeReason.SCHEDULED_CHECK


def hold_ran_out(doc: TodoDocument) -> bool:
    """Return whether an unanswered hold has had all its reminders, so its next wake closes the todo."""
    return (
        doc.waiting_on is WaitingOn.USER
        and doc.if_no_reply is NoReplyPlan.HOLD
        and doc.hold_checks > MAX_HOLD_CHECKS
    )


def _question_wake(doc: TodoDocument) -> WakeReason:
    if doc.if_no_reply is None:
        return WakeReason.QUESTION_EXPIRED
    match doc.if_no_reply:
        case NoReplyPlan.ASK_AGAIN:
            return WakeReason.REASK_DUE
        case NoReplyPlan.PROCEED:
            return WakeReason.DEFAULT_DUE
        case NoReplyPlan.HOLD:
            return WakeReason.HOLD_LAST_CHECK if hold_ran_out(doc) else WakeReason.HOLD_CHECK


def require_open_state(doc: TodoDocument, now: datetime) -> None:
    """Raise OpenStateError when the todo would be left without a valid next step."""
    if problems := open_state_problems(doc, now):
        raise OpenStateError(problems)


def _relative(at: datetime, now: datetime) -> str:
    delta = at - now
    if delta <= timedelta(0):
        return "due now"
    if delta < timedelta(hours=1):
        return f"in {max(1, int(delta.total_seconds() // 60))}m"
    if delta < timedelta(days=1):
        return f"in {int(delta.total_seconds() // 3600)}h"
    return f"in {delta.days}d"


def no_reply_plan_words(doc: TodoDocument) -> str:
    """Say what the todo does when its question expires."""
    if doc.if_no_reply is None:
        return "nothing decided"
    if doc.if_no_reply is NoReplyPlan.PROCEED:
        return f"proceed: {doc.default_action}"
    return _PLAN_WORDS[doc.if_no_reply]


def describe_open_state(doc: TodoDocument, now: datetime) -> str:
    """One phrase saying what the todo waits on and when it next acts."""
    if doc.pause_reason is not None:
        return "paused by the system"
    when = _relative(doc.scheduled_at, now) if doc.scheduled_at else "never"
    if doc.recurrence:
        return f"repeats {doc.recurrence}, next run {when}"
    if doc.waiting_on is None:
        return f"no next step set (next run {when})"
    match doc.waiting_on:
        case WaitingOn.TIME:
            return f"next check {when}"
        case WaitingOn.EVENT:
            return f"waiting on an event, backup check {when}"
        case WaitingOn.USER:
            return (
                f'waiting on the user: "{doc.question}" (expires {when}, '
                f"then {no_reply_plan_words(doc)})"
            )
        case WaitingOn.SUB_TODOS:
            return f"waiting on its sub-todos, backup check {when}"
        case WaitingOn.UNPLANNED:
            return f"not planned yet, plan it {when}"
