"""What a GAIA task's run is told: which task it is, why it woke, and how it must end."""

from app.constants.agents import TODO_REARM_TAG, TODO_WAKES_AGAIN_TAG
from app.constants.todos import WakeReason

# Names the running task, so a run can pass its own id as a subtask's parent_id.
TASK_ID_LINE = "This task's id: {task_id}."

# Added to a scheduled run's brief when the task does not repeat: the check that woke
# this run is spent, so the run must close the task or give it a new next step.
TASK_REARM_BRIEF = (
    f"{TODO_REARM_TAG}\n"
    "WHY YOU WOKE: {why}\n"
    "This run used up the check that woke it. Check the notes' Done when against their "
    "Evidence, then end the run one of these ways: done or no longer worth doing, so "
    "complete_task with the proof in Learnings; or still open, so update_task with "
    "waiting_on and a new next_check ('3d' works). A run that ends without one is sent "
    "back once; after that GAIA parks the task as unplanned for tomorrow and records "
    "that it had to."
)

TASK_WAKES_AGAIN_BRIEF = (
    f"{TODO_WAKES_AGAIN_TAG}\n"
    "This task wakes you again on its own (its repeat, or the app event that woke this run), "
    "so it needs no new check. Do this run's part once, then end it: complete_task when "
    "Done when is met, otherwise finish_task with outcome schedule."
)

# What woke a scheduled run, by WakeReason; filled with the task's own fields.
WAKE_REASON_TEXT: dict[WakeReason, str] = {
    WakeReason.SCHEDULED_CHECK: "your scheduled check came up.",
    WakeReason.BACKUP_CHECK: (
        "your backup check came up and the event this task watches for has not woken it. "
        "Look for it yourself. If it still has not happened, keep waiting with a new "
        "backup check, ask the user one question, or close the task if it no longer matters."
    ),
    WakeReason.SUB_TODO_CHECK: (
        "a subtask finished or your backup check came up. Read your subtasks and "
        "log: when all the work is done, close this task; otherwise set the next check."
    ),
    WakeReason.PLAN_IT: (
        "this task was captured without a plan and the date to plan it came up. Decide what "
        "it waits on and set it (waiting_on plus next_check), ask the user one short "
        "question if only they can say, or close it if it no longer matters."
    ),
    WakeReason.REASK_DUE: (
        'your question expired unanswered: "{question}". You chose to ask again, and this '
        "is the task's one re-ask: ask once more, briefly, then set waiting_on='user' with "
        "if_no_reply 'proceed' (and a default_action) or 'hold'."
    ),
    WakeReason.DEFAULT_DUE: (
        'your question expired unanswered: "{question}". You decided then: {plan}. Carry it '
        "out, tell the user in one line what you did, then close the task or set its next step."
    ),
    WakeReason.HOLD_CHECK: (
        'your question is still unanswered: "{question}" (check {hold_checks} of '
        "{max_hold_checks}). Nothing could move without it. Remind the user in one short "
        "line, then keep waiting_on='user' and set the next check, up to {hold_days} days out."
    ),
    WakeReason.HOLD_LAST_CHECK: (
        'your question went unanswered through {max_hold_checks} checks: "{question}". '
        "Close the task with complete_task and tell the user in one line that you closed "
        "it and why."
    ),
    WakeReason.QUESTION_EXPIRED: (
        'your question expired unanswered: "{question}". Decide now: ask once more, act on '
        "a sensible default and tell the user, or hold until they answer."
    ),
}

# Appended to a run whose task tells the user its results. GAIA reads the run's final
# report and messages the user only when it matters, so the run neither notifies on
# its own nor decides delivery for the user.
DELIVERED_RESULT_RULES = (
    "REPORTING: never call send_notification for this run or change this task's delivery "
    "settings. When this run proves the goal is fully achieved, write Learnings in the "
    "task's notes and call complete_task in this run; never wait for the user to report it."
)

# The report's form for a task whose own guidance sets none.
DELIVERED_RESULT_GUIDANCE = (
    f"{DELIVERED_RESULT_RULES} In your result, say when the user already knows an open "
    "question or asked to hear every result."
)

# The counterpart for a silent task: nothing is delivered, so a result the user needs
# has to be sent deliberately or it is lost in the notes.
SILENT_RUN_GUIDANCE = (
    "DELIVERY: this task is silent, so your final message is NOT sent to the user. "
    "Record the outcome in the task's notes. If something genuinely needs them, "
    "send_notification is the only way to reach them. If the goal is fully achieved, "
    "update the notes' Learnings and call complete_task in the same run instead of "
    "leaving it open."
)

# Heads the Standing rules a subtask's run inherits from its parent.
PARENT_STANDING_RULES_LABEL = (
    "Standing rules of this task's parent: the user's instructions, which this run obeys "
    "like its own (where they conflict, this task's own Standing rules win):"
)

# Tells a subtask when its parent runs next, so it can judge what cannot wait for that run.
PARENT_NEXT_RUN_LINE = "\"{title}\", this task's parent, runs next on {when}, the user's time."

# Heads a parent's open subtasks in its run: they report here instead of to the user.
SUBTASKS_LABEL = (
    "Your open subtasks. They report to you, so their news reaches the user through your "
    "report, except what an email thread's task told the user itself because it could not "
    "wait. Each one's Current State:"
)
# Closes the subtask list when it was cut at its limit, so the run does not take it as whole.
SUBTASKS_CUT_NOTE = (
    '(Only the first {limit} are shown; more are open. list_tasks(parent_id="{task_id}") '
    "lists them.)"
)
