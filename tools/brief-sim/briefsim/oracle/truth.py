"""What the world says each brief should have said: the run's artifacts plus the world rebuilt from its scenario."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import re
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

from briefsim.world.apps.github import issue_url
from briefsim.world.model import App, AppState, CalendarEvent, GithubItem, TodoistTask, World
from briefsim.world.scenario import founder_world

JsonObject = dict[str, object]
#: How long before a brief is stored its source reads happen (scouts, calendar).
READ_WINDOW = timedelta(minutes=20)
_STOPWORDS = frozenset(
    {"the", "a", "an", "to", "for", "with", "of", "on", "and", "about", "your", "my"}
)
#: Share of content words an item and a record must have in common to be the same thing.
_PARAPHRASE_OVERLAP = 0.5
_APP_LABELS = {
    App.CALENDAR: ("google calendar", "googlecalendar", "calendar"),
    App.GITHUB: ("github",),
    App.TODOIST: ("todoist",),
}


class StoredItem(TypedDict, total=False):
    text: str
    detail: str | None
    app: str | None
    url: str | None
    todo_id: str | None


class StoredSection(TypedDict, total=False):
    title: str
    items: list[StoredItem]


class StoredEvent(TypedDict, total=False):
    date: str
    start: str | None
    title: str


class StoredSource(TypedDict, total=False):
    app: str
    reason: str


class StoredPayload(TypedDict, total=False):
    """The slice of GAIA's BriefingPayload the oracle and report read."""

    headline: str
    lede: str
    caption: str
    message: str | None
    sections: list[StoredSection]
    calendar: list[StoredEvent]
    sources_unavailable: list[StoredSource]


class StoredEdition(TypedDict):
    """A brief's stored edition render: the key its image variants are stored under."""

    key: str


class StoredBrief(TypedDict, total=False):
    """A briefings document as run.py exported it (GAIA's BriefingModel, ids and dates as strings)."""

    _id: str
    id: str
    date: str
    kind: str
    created_at: str
    payload: StoredPayload
    delivered_channels: list[str]
    edition: "StoredEdition | None"


def parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read_jsonl(path: Path) -> list[JsonObject]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def app_of_label(label: str) -> App | None:
    lowered = label.lower()
    return next(
        (app for app, names in _APP_LABELS.items() if any(n in lowered for n in names)), None
    )


@dataclass(frozen=True)
class ShownItem:
    """One item a brief printed, with the world record it is about when one can be identified."""

    text: str
    detail: str | None
    app: str | None
    url: str | None
    todo_id: str | None
    section: str
    github: int | None = None
    todoist: str | None = None


@dataclass
class Brief:
    doc: StoredBrief
    stored_at: datetime
    local_date: date
    kind: str
    items: list[ShownItem] = field(default_factory=list)

    @property
    def payload(self) -> StoredPayload:
        return self.doc["payload"]

    def text(self) -> str:
        """Every word the user reads: headline, lede, message and every item."""
        payload = self.payload
        parts = [
            payload.get("headline") or "",
            payload.get("lede") or "",
            payload.get("caption") or "",
            payload.get("message") or "",
        ]
        parts += [f"{i.text} {i.detail or ''}" for i in self.items]
        return "\n".join(parts)


@dataclass
class Truth:
    world: World
    tz: ZoneInfo
    briefs: list[Brief]
    reads: list[JsonObject]
    persona: list[JsonObject]
    connected_at: datetime
    #: The minute past its hour each brief kind is scheduled at (the user's slot minute).
    slot_minutes: dict[str, int] = field(default_factory=dict)

    def state_at(self, at: datetime) -> AppState:
        return self.world.state_at(at)

    def read_outcomes(self, brief: Brief) -> dict[App, set[str]]:
        """Return each app's read outcomes (ok or a fault mode) in the run that stored brief."""
        start = brief.stored_at - READ_WINDOW
        outcomes: dict[App, set[str]] = {}
        for row in self.reads:
            at = parse_instant(str(row["at"]))
            if start <= at <= brief.stored_at:
                outcomes.setdefault(App(str(row["app"])), set()).add(str(row["outcome"]))
        return outcomes

    def previous(self, brief: Brief) -> Brief | None:
        earlier = [b for b in self.briefs if b.kind == brief.kind and b.stored_at < brief.stored_at]
        return earlier[-1] if earlier else None

    def local_day_events(self, brief: Brief) -> list[CalendarEvent]:
        """Return the confirmed events overlapping the brief's local day, as the world held them when it ran."""
        state = self.state_at(brief.stored_at)
        start = datetime.combine(brief.local_date, datetime.min.time(), self.tz)
        end = start + timedelta(days=1)
        hits = []
        for event in state.calendar.values():
            if event.status != "confirmed":
                continue
            if event.all_day is not None:
                if event.all_day == brief.local_date:
                    hits.append(event)
            elif (
                event.start is not None
                and event.end is not None
                and event.end > start
                and event.start < end
            ):
                hits.append(event)
        return hits

    def gaia_todos(self, at: datetime) -> list[JsonObject]:
        """Return the persona's GAIA todos still open at the instant at."""
        open_todos: dict[str, JsonObject] = {}
        for row in self.persona:
            if parse_instant(str(row["at"])) > at:
                break
            if row["action"] == "add_todo":
                open_todos[str(row["todo_id"])] = row
            elif row["action"] == "complete_todo" and "todo_id" in row:
                open_todos.pop(str(row["todo_id"]), None)
        return list(open_todos.values())


def _github_number(url: str | None, state: AppState) -> int | None:
    if not url:
        return None
    match = re.search(r"/(?:issues|pull)/(\d+)", url)
    if match and int(match.group(1)) in state.github:
        return int(match.group(1))
    return None


def words(text: str) -> frozenset[str]:
    """Return the content words of text, lowercased: what two phrasings of one title share."""
    return frozenset(w for w in re.findall(r"[^\W_]+", text.lower()) if w not in _STOPWORDS)


def _todoist_id(text: str, state: AppState) -> str | None:
    """Return the one open task the item paraphrases (the brief renames "Send the X" to "X")."""
    said = words(text)
    scored = []
    for task in state.todoist.values():
        if task.content is None or task.deleted:
            continue
        title = words(task.content)
        overlap = len(said & title) / max(len(said | title), 1)
        if overlap >= _PARAPHRASE_OVERLAP:
            scored.append((overlap, task.id))
    scored.sort(reverse=True)
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


def _github_by_title(text: str, state: AppState) -> int | None:
    lowered = text.lower()
    hits = [
        i.number
        for i in state.github.values()
        if i.title.lower() in lowered or lowered in i.title.lower()
    ]
    return hits[0] if len(hits) == 1 else None


def _items(payload: StoredPayload, state: AppState) -> list[ShownItem]:
    shown: list[ShownItem] = []
    for section in payload.get("sections") or []:
        for item in section.get("items") or []:
            text, url, app = item.get("text") or "", item.get("url"), item.get("app")
            source = app_of_label(app) if app else None
            number = _github_number(url, state)
            if number is None and source is App.GITHUB:
                number = _github_by_title(text, state)
            task = _todoist_id(text, state) if source is App.TODOIST else None
            shown.append(
                ShownItem(
                    text,
                    item.get("detail"),
                    app,
                    url,
                    item.get("todo_id"),
                    section.get("title") or "",
                    number,
                    task,
                )
            )
    return shown


def load(out: Path) -> Truth:
    run = json.loads((out / "run.json").read_text())
    origin = parse_instant(run["origin"])
    world = founder_world(origin, int(run["days"]))
    tz = ZoneInfo(run["timezone"])
    persona = read_jsonl(out / "persona.jsonl")
    connected = next(parse_instant(str(r["at"])) for r in persona if r["action"] == "connect")
    briefs = []
    docs = cast(list[StoredBrief], read_jsonl(out / "briefings.jsonl"))
    for doc in sorted(docs, key=lambda d: d["created_at"]):
        stored = parse_instant(doc["created_at"])
        brief = Brief(doc, stored, date.fromisoformat(doc["date"]), doc["kind"])
        brief.items = _items(brief.payload, world.state_at(stored))
        briefs.append(brief)
    reads = [r for r in read_jsonl(out / "world_calls.jsonl") if r.get("kind") == "read"]
    return Truth(world, tz, briefs, reads, persona, connected, _slot_minutes(out))


_BRIEF_WORKFLOW_KINDS = {"daily_briefing": "daily", "weekly_digest": "weekly"}


def _slot_minutes(out: Path) -> dict[str, int]:
    """Return each brief kind's scheduled minute, from its workflow's stored cron."""
    minutes: dict[str, int] = {}
    for row in read_jsonl(out / "workflows.jsonl"):
        kind = _BRIEF_WORKFLOW_KINDS.get(str(row.get("system_workflow_key")))
        trigger = cast(JsonObject, row.get("trigger_config") or {})
        cron = trigger.get("cron_expression")
        if kind and isinstance(cron, str):
            minutes[kind] = int(cron.split(" ", 1)[0])
    return minutes


def github_item(truth: Truth, brief: Brief, number: int) -> GithubItem:
    return truth.state_at(brief.stored_at).github[number]


def todoist_task(truth: Truth, brief: Brief, task_id: str) -> TodoistTask:
    return truth.state_at(brief.stored_at).todoist[task_id]


__all__ = [
    "Brief",
    "ShownItem",
    "Truth",
    "app_of_label",
    "github_item",
    "issue_url",
    "load",
    "todoist_task",
]
