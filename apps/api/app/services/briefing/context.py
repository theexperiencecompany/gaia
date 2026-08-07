"""Context gathering + formatting for the briefing run.

The service does deterministic work (curation, persistence, delivery); this
module reads the world the agent needs to see and formats it into the prompt
blocks. Every block is plain text — the agent turns it into the payload.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.constants.briefing import BRIEFING_KIND_DAILY, WINBACK_THRESHOLD
from app.constants.todos import (
    ASSIGNEE_GAIA,
    FACET_NOTES,
    facet_from_doc,
)
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.briefing_models import BriefingKind, BriefingMood, BriefingPayload
from app.models.todo_models import ExecutionStatus, Priority, TodoDocument
from app.services.briefing import dormancy
from shared.py.wide_events import log

# GAIA todos that are live work (shown in the plan block).
_OPEN_GAIA_STATUSES = [
    ExecutionStatus.PROPOSED.value,
    ExecutionStatus.QUEUED.value,
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.NEEDS_YOU.value,
]


@dataclass
class UserClock:
    tz: ZoneInfo
    now_local: datetime
    date_str: str
    day_of_year: int


@dataclass
class WinbackState:
    unacknowledged: int
    last_was_winback: bool

    @property
    def is_winback(self) -> bool:
        return self.unacknowledged >= WINBACK_THRESHOLD

    @property
    def should_back_off(self) -> bool:
        # A winback already went out and the user is still silent — don't repeat
        # it the next day; back off until there's activity.
        return self.last_was_winback and self.unacknowledged >= WINBACK_THRESHOLD


@dataclass
class CompletedWork:
    gaia: list[TodoDocument] = field(default_factory=list)
    user: list[TodoDocument] = field(default_factory=list)


def resolve_clock(user_timezone: str | None) -> UserClock:
    tz = ZoneInfo(user_timezone or "UTC")
    now_local = datetime.now(tz)
    return UserClock(
        tz=tz,
        now_local=now_local,
        date_str=now_local.date().isoformat(),
        day_of_year=now_local.timetuple().tm_yday,
    )


def day_start_utc(clock: UserClock, days_ago: int = 0) -> datetime:
    day = clock.now_local.date() - timedelta(days=days_ago)
    return datetime.combine(day, time.min, tzinfo=clock.tz).astimezone(UTC)


async def get_yesterday_payload(
    user_id: str, before_date: str, kind: BriefingKind = BRIEFING_KIND_DAILY
) -> BriefingPayload | None:
    """Latest daily briefing payload strictly before ``before_date`` (today).

    Excludes today so a same-day re-run compares against the real prior brief,
    not itself.
    """
    briefing = await briefing_repository.get_before_date(
        user_id, kind=kind, before_date=before_date
    )
    return briefing.payload if briefing else None


# Users type junk into onboarding ("nothing", "n/a"); junk is not a goal.
_JUNK_FOCUS_VALUES = {"nothing", "none", "n/a", "na", "-", "idk", "no"}


def has_meaningful_focus(focus: str | None) -> bool:
    """Whether the onboarding focus is a real stated goal (not blank or junk)."""
    cleaned = (focus or "").strip()
    return bool(cleaned) and cleaned.lower() not in _JUNK_FOCUS_VALUES


async def format_goal_block(user_id: str, user: dict) -> tuple[str, bool]:
    """Return (formatted goal block, has_goal). ``has_goal`` gates cold-start."""
    focus = ((user.get("onboarding") or {}).get("focus") or "").strip()
    if not has_meaningful_focus(focus):
        focus = ""
    lines: list[str] = []
    if focus:
        lines.append(f"Stated goal: {focus}")

    try:
        result = await memory_engine.recall(
            user_id, "what is the user currently working on and their goals", limit=5
        )
        for entry in result.memories:
            note = entry_to_note(entry).strip()
            if note and note not in lines:
                lines.append(f"- {note}")
    except Exception as exc:
        # Memory recall is best-effort context, not a hard dependency of the run.
        log.warning("briefing.goal_block_recall_failed", user_id=user_id, error=str(exc))

    if not lines:
        return (
            "No stated goal on record yet — treat goal discovery as part of today's job.",
            False,
        )
    return ("\n".join(lines), bool(focus) or len(lines) > 0)


@dataclass
class GoalLane:
    """One goal's world: the lane the nightly pass advances and the brief reports."""

    goal_id: str
    title: str
    canvas_excerpt: str
    completed: list[TodoDocument] = field(default_factory=list)
    staged: list[TodoDocument] = field(default_factory=list)
    running: list[TodoDocument] = field(default_factory=list)
    failed: list[TodoDocument] = field(default_factory=list)
    needs_you: list[TodoDocument] = field(default_factory=list)


_LANE_CANVAS_EXCERPT_CHARS = 700
# The nightly pass writes its freshest thinking into these sections, so they lead
# the excerpt regardless of where they sit in the notes facet.
_PRIORITY_CANVAS_SECTIONS = ("current state", "next steps")


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, block) pairs by ``## `` headers.

    Each block keeps its own heading line; text before the first header is
    returned under an empty heading.
    """
    sections: list[tuple[str, str]] = []
    heading = ""
    buf: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("## "):
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading = line.lstrip()[3:].strip()
            buf = [line]
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))
    return sections


def _excerpt_canvas(notes: str) -> str:
    """The freshest slice of a goal's notes facet for the night shift to plan from.

    A head-truncation converges on the oldest plan text as the notes grow, hiding
    exactly the ``## Current State`` the nightly pass should plan from. So the
    priority sections lead, the rest of the budget is filled from the top of
    everything else, and when no such sections exist the tail (most recently
    appended) wins over the head.
    """
    notes = notes.strip()
    if len(notes) <= _LANE_CANVAS_EXCERPT_CHARS:
        return notes
    sections = _split_markdown_sections(notes)
    priority = [b for h, b in sections if h.lower() in _PRIORITY_CANVAS_SECTIONS]
    if not priority:
        return notes[-_LANE_CANVAS_EXCERPT_CHARS:].strip()
    rest = [b for h, b in sections if h.lower() not in _PRIORITY_CANVAS_SECTIONS]
    excerpt = "\n\n".join(priority).strip()
    if rest and len(excerpt) < _LANE_CANVAS_EXCERPT_CHARS:
        excerpt += "\n\n" + "\n\n".join(rest).strip()
    return excerpt[:_LANE_CANVAS_EXCERPT_CHARS].strip()


async def gather_goal_lanes(user_id: str, since: datetime) -> list[GoalLane]:
    """Every active goal with its children by execution state.

    This is the deterministic world the briefing reports and the night shift
    advances: state lives here, never in per-run memory recall. Goals are
    backstage data only — recurring goal work is a GAIA todo with recurrence,
    never a goal-linked workflow (see the unified-todo-model spec).
    """
    lanes: list[GoalLane] = []
    for goal in await todo_repository.list_open_goals(user_id):
        # A goal's living strategy is its notes facet (its working memory).
        goal_notes = facet_from_doc(goal.model_dump(), FACET_NOTES, allow_canvas_fallback=False)
        lane = GoalLane(
            goal_id=goal.id,
            title=goal.title or "untitled goal",
            canvas_excerpt=_excerpt_canvas(goal_notes),
        )
        for child in await todo_repository.list_goal_children(user_id, goal.id):
            status = child.execution_status.value if child.execution_status else None
            if child.completed_at and child.completed_at >= since:
                lane.completed.append(child)
            elif status == "proposed":
                lane.staged.append(child)
            elif status in ("queued", "running"):
                lane.running.append(child)
            elif status == "failed":
                lane.failed.append(child)
            elif status == "needs_you":
                lane.needs_you.append(child)
        lanes.append(lane)
    return lanes


def format_goal_lanes_block(lanes: list[GoalLane]) -> str:
    """Render lanes for the night-shift prompt: state in, judgment out."""
    if not lanes:
        return "No active goals."
    parts: list[str] = []
    for lane in lanes:
        lines = [f'GOAL "{lane.title}" (goal_id: {lane.goal_id})']
        if lane.canvas_excerpt.strip():
            lines.append(f"strategy canvas:\n{lane.canvas_excerpt.strip()}")
        for label, docs in (
            ("done since yesterday", lane.completed),
            ("open work", lane.running),
            ("staged proposals", lane.staged),
            ("failed", lane.failed),
            ("blocked on the user", lane.needs_you),
        ):
            if docs:
                lines.append(label + ": " + "; ".join(d.title or "?" for d in docs))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def gather_completed_since(user_id: str, since: datetime) -> CompletedWork:
    work = CompletedWork()
    for doc in await todo_repository.list_completed_since(user_id, since=since):
        (work.gaia if doc.assignee == ASSIGNEE_GAIA else work.user).append(doc)
    return work


async def format_todos_block(user_id: str) -> str:
    gaia_docs = await todo_repository.list_open_gaia_by_status(
        user_id, statuses=_OPEN_GAIA_STATUSES, limit=20
    )
    gaia_lines = [
        f"- [GAIA · {d.execution_status.value if d.execution_status else None}] {d.title or 'untitled'}"
        + (f" (serves: {d.serves})" if d.serves else "")
        for d in gaia_docs
    ]

    user_docs = await todo_repository.list_open_user_todos(user_id, limit=20)
    user_lines = [
        f"- [YOU] {d.title or 'untitled'}"
        + (f" (priority: {d.priority.value})" if d.priority != Priority.NONE else "")
        for d in user_docs
    ]

    if not gaia_lines and not user_lines:
        return "Current list: EMPTY — no open todos on either side."
    parts = ["Current open todos:"]
    if gaia_lines:
        parts.append("GAIA-assigned:\n" + "\n".join(gaia_lines))
    if user_lines:
        parts.append("Yours:\n" + "\n".join(user_lines))
    return "\n\n".join(parts)


async def user_open_todo_summary(user_id: str) -> tuple[int, list[str]]:
    """Count + first titles of the user's own open todos, for the brief's facts.

    The voice pass gets these so an empty-lane day can't be voiced as "all
    clear" while the user's own list still has work in it.
    """
    docs = await todo_repository.list_open_user_todos(user_id, limit=50)
    titles = [d.title or "untitled" for d in docs]
    return len(titles), titles[:5]


async def format_lookback_block(
    user_id: str, yesterday_payload: BriefingPayload | None, since: datetime
) -> str:
    completed = await gather_completed_since(user_id, since)
    executions = await workflow_executions_repository.list_since(user_id, since, limit=20)

    parts: list[str] = []
    if yesterday_payload:
        planned = [item.text for section in yesterday_payload.sections for item in section.items]
        if planned:
            parts.append(
                "Yesterday you told the user you'd focus on:\n"
                + "\n".join(f"- {p}" for p in planned if p)
            )
    else:
        parts.append("No prior briefing — this is the first look-back.")

    if completed.gaia or completed.user:
        done = [f"- GAIA finished: {d.title or 'untitled'}" for d in completed.gaia]
        done += [f"- You finished: {d.title or 'untitled'}" for d in completed.user]
        parts.append("Actually completed since then:\n" + "\n".join(done))
    else:
        parts.append("Nothing was completed since the last briefing.")

    if executions:
        # workflow_executions carries no workflow_title field; "Workflow" is the
        # generic label every run has used for as long as the field's been gone.
        ex_lines = [
            f"- Workflow [{d.status}]" + (f": {d.summary}" if d.summary else "") for d in executions
        ]
        parts.append("Background workflow runs since then:\n" + "\n".join(ex_lines))

    return "\n\n".join(parts)


async def compute_winback_state(user_id: str, recent: int = 10) -> WinbackState:
    """Count consecutive most-recent daily briefings the user never acknowledged.

    Acknowledgement is honest and channel-agnostic: the briefing was opened, OR the
    user was active since it went out (a reactivation signal — goal created, session
    active, or any message). A todo completing is deliberately NOT an ack: GAIA's
    night shift completes its own todos autonomously, so counting completions would
    let GAIA acknowledge its own briefings and winback would never fire.

    The loop breaks at the first acknowledged briefing, so the reactivation-signal
    lookup runs only for the unacknowledged tail (at most one extra call past it).
    """
    briefings = await briefing_repository.list_recent(
        user_id, limit=recent, kind=BRIEFING_KIND_DAILY
    )
    if not briefings:
        return WinbackState(unacknowledged=0, last_was_winback=False)

    unacknowledged = 0
    for briefing in briefings:
        created_at = briefing.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        acknowledged = briefing.opened_at is not None or await dormancy.reactivation_signal_since(
            user_id, created_at
        )
        if acknowledged:
            break
        unacknowledged += 1

    last_mood: BriefingMood | str = briefings[0].payload.mood
    return WinbackState(unacknowledged=unacknowledged, last_was_winback=last_mood == "winback")
