"""Tasks: the one record for work the user or GAIA does, once or on repeat."""

from datetime import timedelta
from enum import StrEnum
import re
from typing import Final

#: A new task's id: this prefix and 12 hex characters. Migrated tasks keep their own id.
TASK_ID_PREFIX: Final = "task_"
TASK_ID_HEX_CHARS: Final = 12
#: Every id a task may carry: a new task's, a migrated workflow's, or a migrated todo's ObjectId.
TASK_ID_PATTERN: Final = re.compile(r"task_[0-9a-f]{12}|wf_[0-9a-f]{12}|[0-9a-f]{24}")

#: The Inbox desk's system key; the desk is the one system task that came from a todo.
INBOX_DESK_SYSTEM_KEY: Final = "gmail:inbox_desk"

#: The trigger name an imported run record carries: it came from a todo's activity log.
IMPORTED_RUN_TRIGGER: Final = "imported_activity"

# Cadence floors per watch source rung (see WatchSource).
WATCH_CADENCE_FLOOR_API: Final = timedelta(minutes=1)
WATCH_CADENCE_FLOOR_PAGE: Final = timedelta(minutes=15)
WATCH_CADENCE_FLOOR_BROWSER: Final = timedelta(minutes=30)
WATCH_CADENCE_FLOOR_AGENT: Final = timedelta(minutes=60)
#: How long a watch lives before it must be renewed.
WATCH_DEFAULT_LIFETIME: Final = timedelta(days=90)
#: Blind checks before the user hears about it, once per episode.
WATCH_BLIND_CHECKS_BEFORE_TELLING: Final = 2
#: How long a watch stays blind before it pauses itself.
WATCH_BLIND_PAUSE_AFTER: Final = timedelta(hours=72)
#: The gap between a scraped reading and the read that confirms it.
WATCH_CONFIRM_GAP: Final = timedelta(minutes=1)


class Assignee(StrEnum):
    """Who does a task: the user (a to-do), or GAIA."""

    USER = "user"
    GAIA = "gaia"


class WhenKind(StrEnum):
    """What brings a task round: nothing, a date, a schedule, an app event, or a watched change."""

    NONE = "none"
    DATE = "date"
    REPEAT = "repeat"
    EVENT = "event"
    WATCH = "watch"


class TaskRunState(StrEnum):
    """Whether a GAIA task is idle, mid-run, or finished every run it will ever make."""

    IDLE = "idle"
    RUNNING = "running"
    ENDED = "ended"


class TaskFlag(StrEnum):
    """A state a task is in that the engine or GAIA's prompts read; formerly a system label."""

    #: Retries ran out; nothing runs the task until the user resets it.
    FAILED = "failed"
    #: An app the task watches lost its connection, or GAIA marked it blocked on something outside.
    BLOCKED = "blocked"
    #: The user waits on the other side of an email thread; a reply unblocks it.
    WAITING_FOR_REPLY = "waiting_for_reply"
    #: GAIA marked the task as waiting on an approval; an event can unblock it.
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    #: The user owes a reply on the thread.
    NEEDS_REPLY = "needs_reply"
    #: The user must act outside the thread (pay, secure, renew); nobody awaits a reply.
    ACTION_NEEDED = "action_needed"


#: Flags that mean the task waits on something outside GAIA.
BLOCKING_FLAGS: Final = frozenset(
    {TaskFlag.BLOCKED, TaskFlag.WAITING_FOR_REPLY, TaskFlag.WAITING_FOR_APPROVAL}
)


class WatchTemplate(StrEnum):
    """The typed shapes a watch's condition takes; there are no free-form operators."""

    THRESHOLD = "threshold"
    STATE = "state"
    NEW_ITEMS = "new_items"
    REPLY_BY = "reply_by"
    UPTIME = "uptime"
    OPEN = "open"


class WatchSourceRung(StrEnum):
    """Where a watch reads its value, cheapest first."""

    CONNECTOR = "connector"
    API = "api"
    FEED = "feed"
    PAGE = "page"
    BROWSER = "browser"
    AGENT = "agent"


#: Rungs whose readings are scraped and need a second, confirming read.
SCRAPED_RUNGS: Final = frozenset({WatchSourceRung.PAGE, WatchSourceRung.BROWSER})

WATCH_CADENCE_FLOORS: Final[dict[WatchSourceRung, timedelta]] = {
    WatchSourceRung.CONNECTOR: WATCH_CADENCE_FLOOR_API,
    WatchSourceRung.API: WATCH_CADENCE_FLOOR_API,
    WatchSourceRung.FEED: WATCH_CADENCE_FLOOR_API,
    WatchSourceRung.PAGE: WATCH_CADENCE_FLOOR_PAGE,
    WatchSourceRung.BROWSER: WATCH_CADENCE_FLOOR_BROWSER,
    WatchSourceRung.AGENT: WATCH_CADENCE_FLOOR_AGENT,
}


class ThresholdDirection(StrEnum):
    ABOVE = "above"
    BELOW = "below"


class WatchTell(StrEnum):
    """When a watch tells the user: on the first match, or on every new match."""

    FIRST_MATCH = "first_match"
    EVERY_MATCH = "every_match"


class WatchEnd(StrEnum):
    """What ends a watch, besides its expiry."""

    FIRST_ALERT = "first_alert"
    TERMINAL_VALUE = "terminal_value"
    REPLY = "reply"
    DEADLINE = "deadline"
    EXPIRY_ONLY = "expiry_only"


class WatchReading(StrEnum):
    """What the last check of a watch saw; blind is never unchanged and never fires."""

    MATCHED = "matched"
    QUIET = "quiet"
    BLIND = "blind"


class TaskRunStatus(StrEnum):
    """How one run of a GAIA task went: running until its one terminal write."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TaskRunKind(StrEnum):
    """A run, or a stretch of a migrated todo's timeline that was no run."""

    RUN = "run"
    HISTORY = "history"


class TemplateOrigin(StrEnum):
    """Where a template came from: a user's publish, or GAIA's curated set."""

    COMMUNITY = "community"
    CURATED = "curated"


# The engine: one job runs a GAIA task, or brings a to-do round, at the task's next time.

#: The ARQ job that brings a task round; also the prefix of its per-occurrence job id.
RUN_TASK_JOB: Final = "run_task"
#: The ARQ job that continues a GAIA task's run parked on an approval the user decided.
RESUME_TASK_JOB: Final = "resume_task"
#: How many due tasks one recovery pass re-arms; the next pass takes the rest.
RECOVER_TASKS_BATCH: Final = 100
#: The most a re-armed job is spread out, so one recovery pass does not fire everything at once.
RECOVER_TASKS_JITTER_SECONDS: Final = 60
#: What a nudge says under a to-do's title when it falls due.
TODO_DUE_NUDGE_BODY: Final = "This is due now."
#: What a nudge says when a repeating to-do comes back onto the list.
TODO_REPEAT_NUDGE_BODY: Final = "This is back on your list."
#: What a task's notify subscription tells the user when its event lands.
TASK_EVENT_NOTIFY_TITLE: Final = "Update on: {title}"
TASK_EVENT_NOTIFY_BODY: Final = "An event you were watching ({trigger_name}) just fired."
#: The page a notification about a task opens.
TASK_DEEP_LINK: Final = "/tasks?taskId={task_id}"
TASKS_PAGE: Final = "/tasks"
VIEW_TASK_LABEL: Final = "View task"

#: How long a GAIA task's run may stay running before recovery takes it as a dead worker's.
STALE_RUN_AFTER: Final = timedelta(minutes=45)
#: How soon a run that found its chat busy with another run checks again.
EXECUTOR_BUSY_RECHECK: Final = timedelta(minutes=1)
#: The durable job that finishes a run's delivery when the task store failed it in-process.
FINISH_TASK_RUN_JOB: Final = "finish_task_run"
FINISH_TASK_RUN_JOB_PREFIX: Final = "task-run-finish:"
#: How much of a run's final report its run record keeps as the summary.
RUN_SUMMARY_CHARS: Final = 500
#: How many earlier runs a run's prompt and its delivery note read.
RECENT_RUNS_READ: Final = 3
#: The surface a paywalled GAIA task run is attributed to in the funnel.
PAYWALL_FEATURE_GAIA_TASK: Final = "gaia_task"


class TaskRunTrigger(StrEnum):
    """What started one run of a GAIA task, as its run record names it."""

    SCHEDULE = "schedule"
    APP_EVENT = "app_event"
    WAIT_MET = "wait_met"
    APPROVAL = "approval"
    SUBTASK = "subtask"
    MANUAL = "manual"


class TaskLogEvent(StrEnum):
    """A lifecycle event the engine writes to a GAIA task's log, as "- <iso> [event] detail"."""

    CREATED = "created"
    SCHEDULED = "scheduled"
    WAITING_CHANGED = "waiting_changed"
    RETRY_SCHEDULED = "retry_scheduled"
    MARKED_FAILED = "marked_failed"
    OPEN_STATE_REPAIRED = "open_state_repaired"
    PAUSED = "paused"
    COMPLETED = "completed"
    SUBTASK_COMPLETED = "subtask_completed"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    RESUME_DROPPED = "resume_dropped"
    MAINTENANCE = "maintenance"
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    #: An app event matched a subscription and was taken for a run.
    APP_EVENT = "app_event"
    #: An app event reached the task and was lost: it could not be kept for a run.
    APP_EVENT_DROPPED = "app_event_dropped"
    RESUMED = "resumed"


class TaskRunDeliveryOutcome(StrEnum):
    """What became of a GAIA task run's result, for its run record and analytics."""

    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"
    SILENCED = "silenced"
    NOTHING_TO_REPORT = "nothing_to_report"
    NOTIFY_OFF = "notify_off"
    NARRATION_FAILED = "narration_failed"


# Repeat shortcuts: intervals step from now (drift is fine); anchored steps keep the wall-clock time.
REPEAT_INTERVALS: Final[dict[str, timedelta]] = {
    "every_4h": timedelta(hours=4),
    "every_1h": timedelta(hours=1),
}
REPEAT_ANCHORED: Final[dict[str, timedelta]] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}
REPEAT_SHORTCUTS: Final = frozenset(REPEAT_INTERVALS.keys() | REPEAT_ANCHORED.keys())

# The task search index (the Chroma collection CHROMA_TASKS_COLLECTION).
#: The most tasks one search returns.
TASK_SEARCH_LIMIT: Final = 10
#: How much of a matched task's notes or details a search shows.
TASK_SEARCH_EXCERPT_CHARS: Final = 400
#: Tasks read or written per index call when reindexing or checking coverage.
TASK_INDEX_BATCH: Final = 200
