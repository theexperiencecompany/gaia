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
    FACET_NOTES,
    facet_from_doc,
    gaia_assigned_filter,
    user_assigned_filter,
)
from app.db.mongodb.collections import (
    briefings_collection,
    todos_collection,
    workflow_executions_collection,
    workflows_collection,
)
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.briefing_models import BriefingMood
from app.models.todo_models import ExecutionStatus
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
    gaia: list[dict] = field(default_factory=list)
    user: list[dict] = field(default_factory=list)


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
    user_id: str, before_date: str, kind: str = BRIEFING_KIND_DAILY
) -> dict | None:
    """Latest daily briefing payload strictly before ``before_date`` (today).

    Excludes today so a same-day re-run compares against the real prior brief,
    not itself. ``date`` is ISO ``YYYY-MM-DD`` so the lexical ``$lt`` is correct.
    """
    doc = await briefings_collection.find_one(
        {"user_id": user_id, "kind": kind, "date": {"$lt": before_date}},
        sort=[("date", -1)],
    )
    return doc.get("payload") if doc else None


async def format_goal_block(user_id: str, user: dict) -> tuple[str, bool]:
    """Return (formatted goal block, has_goal). ``has_goal`` gates cold-start."""
    focus = ((user.get("onboarding") or {}).get("focus") or "").strip()
    # Users type junk into onboarding ("nothing", "n/a"); junk is not a goal.
    if focus.lower() in {"nothing", "none", "n/a", "na", "-", "idk", "no"}:
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
    completed: list[dict] = field(default_factory=list)
    staged: list[dict] = field(default_factory=list)
    running: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    needs_you: list[dict] = field(default_factory=list)
    workflows: list[dict] = field(default_factory=list)


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
    """Every active goal with its children, linked workflows, and latest runs.

    This is the deterministic world the briefing reports and the night shift
    advances: state lives here, never in per-run memory recall.
    """
    lanes: list[GoalLane] = []
    async for goal in todos_collection.find(
        {"user_id": user_id, "kind": "goal", "completed": False},
        {"title": 1, "notes_content": 1, "canvas_content": 1},
    ).sort("created_at", 1):
        goal_id = str(goal["_id"])
        # A goal's living strategy is its notes facet (its working memory).
        goal_notes = facet_from_doc(goal, FACET_NOTES, allow_canvas_fallback=False)
        lane = GoalLane(
            goal_id=goal_id,
            title=goal.get("title", "untitled goal"),
            canvas_excerpt=_excerpt_canvas(goal_notes),
        )
        async for child in todos_collection.find(
            {"user_id": user_id, "goal_id": goal_id},
            {
                "title": 1,
                "execution_status": 1,
                "deliverable_content": 1,
                "notes_content": 1,
                "canvas_content": 1,
                "completed_at": 1,
                "error_message": 1,
            },
        ):
            status = child.get("execution_status")
            if child.get("completed_at") and child["completed_at"] >= since:
                lane.completed.append(child)
            elif status == "proposed":
                lane.staged.append(child)
            elif status in ("queued", "running"):
                lane.running.append(child)
            elif status == "failed":
                lane.failed.append(child)
            elif status == "needs_you":
                lane.needs_you.append(child)
        async for wf in workflows_collection.find(
            {
                "user_id": user_id,
                "source_todo_id": goal_id,
                "activated": True,
                # Per-todo execution plumbing is not a rhythm workflow.
                "is_todo_workflow": {"$ne": True},
            },
            {"title": 1, "id": 1},
        ):
            wf_id = wf.get("id") or str(wf.get("_id"))
            last = await workflow_executions_collection.find_one(
                {"workflow_id": wf_id}, sort=[("started_at", -1)]
            )
            lane.workflows.append(
                {
                    "title": wf.get("title", "workflow"),
                    "last_status": (last or {}).get("status"),
                    "last_run": (last or {}).get("started_at"),
                }
            )
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
                lines.append(label + ": " + "; ".join(d.get("title", "?") for d in docs))
        for wf in lane.workflows:
            lines.append(f"workflow '{wf['title']}': last run {wf['last_status'] or 'never'}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def gather_completed_since(
    user_id: str, since: datetime, *, include_deliverables: bool = False
) -> CompletedWork:
    projection = {"title": 1, "assignee": 1, "labels": 1, "completed_at": 1, "serves": 1}
    if include_deliverables:
        # The weekly digest voices deliverable snippets; the daily look-back only
        # needs titles, so it skips the heavier facet fields.
        projection |= {"deliverable_content": 1, "canvas_content": 1}
    work = CompletedWork()
    cursor = todos_collection.find(
        {"user_id": user_id, "completed_at": {"$gte": since}}, projection
    )
    async for doc in cursor:
        is_gaia = doc.get("assignee") == "gaia" or "gaia-tracked" in doc.get("labels", [])
        (work.gaia if is_gaia else work.user).append(doc)
    return work


async def format_todos_block(user_id: str) -> str:
    gaia_cursor = todos_collection.find(
        {
            "user_id": user_id,
            "execution_status": {"$in": _OPEN_GAIA_STATUSES},
            **gaia_assigned_filter(),
        },
        {"title": 1, "execution_status": 1, "serves": 1},
    ).limit(20)
    gaia_lines = [
        f"- [GAIA · {d.get('execution_status')}] {d.get('title', 'untitled')}"
        + (f" (serves: {d['serves']})" if d.get("serves") else "")
        async for d in gaia_cursor
    ]

    user_cursor = todos_collection.find(
        {"user_id": user_id, "completed": False, **user_assigned_filter()},
        {"title": 1, "priority": 1},
    ).limit(20)
    user_lines = [
        f"- [YOU] {d.get('title', 'untitled')}"
        + (f" (priority: {d['priority']})" if d.get("priority") not in (None, "none") else "")
        async for d in user_cursor
    ]

    if not gaia_lines and not user_lines:
        return "Current list: EMPTY — no open todos on either side."
    parts = ["Current open todos:"]
    if gaia_lines:
        parts.append("GAIA-assigned:\n" + "\n".join(gaia_lines))
    if user_lines:
        parts.append("Yours:\n" + "\n".join(user_lines))
    return "\n\n".join(parts)


async def format_lookback_block(
    user_id: str, yesterday_payload: dict | None, since: datetime
) -> str:
    completed = await gather_completed_since(user_id, since)
    exec_cursor = workflow_executions_collection.find(
        {"user_id": user_id, "started_at": {"$gte": since}},
        {"workflow_title": 1, "status": 1, "summary": 1},
    ).limit(20)
    executions = [doc async for doc in exec_cursor]

    parts: list[str] = []
    if yesterday_payload:
        planned = []
        for section in yesterday_payload.get("sections", []):
            for item in section.get("items", []):
                planned.append(item.get("text", ""))
        if planned:
            parts.append(
                "Yesterday you told the user you'd focus on:\n"
                + "\n".join(f"- {p}" for p in planned if p)
            )
    else:
        parts.append("No prior briefing — this is the first look-back.")

    if completed.gaia or completed.user:
        done = [f"- GAIA finished: {d.get('title', 'untitled')}" for d in completed.gaia]
        done += [f"- You finished: {d.get('title', 'untitled')}" for d in completed.user]
        parts.append("Actually completed since then:\n" + "\n".join(done))
    else:
        parts.append("Nothing was completed since the last briefing.")

    if executions:
        ex_lines = [
            f"- {d.get('workflow_title') or 'Workflow'} [{d.get('status')}]"
            + (f": {d['summary']}" if d.get("summary") else "")
            for d in executions
        ]
        parts.append("Background workflow runs since then:\n" + "\n".join(ex_lines))

    return "\n\n".join(parts)


async def compute_winback_state(user_id: str, recent: int = 10) -> WinbackState:
    """Count consecutive most-recent daily briefings the user never acknowledged.

    Acknowledgement is honest and channel-agnostic: the briefing was opened, OR a
    real todo completed after it went out (the user acted on the loop).
    """
    briefings = (
        await briefings_collection.find(
            {"user_id": user_id, "kind": BRIEFING_KIND_DAILY},
            {"created_at": 1, "opened_at": 1, "payload": 1},
        )
        .sort("created_at", -1)
        .limit(recent)
        .to_list(length=recent)
    )
    if not briefings:
        return WinbackState(unacknowledged=0, last_was_winback=False)

    latest_completion = await todos_collection.find_one(
        {"user_id": user_id, "completed_at": {"$ne": None}},
        {"completed_at": 1},
        sort=[("completed_at", -1)],
    )
    last_completed_at = latest_completion.get("completed_at") if latest_completion else None

    unacknowledged = 0
    for doc in briefings:
        acknowledged = doc.get("opened_at") is not None or (
            last_completed_at is not None and last_completed_at > doc["created_at"]
        )
        if acknowledged:
            break
        unacknowledged += 1

    last_mood: BriefingMood | str = (briefings[0].get("payload") or {}).get("mood", "")
    return WinbackState(unacknowledged=unacknowledged, last_was_winback=last_mood == "winback")
