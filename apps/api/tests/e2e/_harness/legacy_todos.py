"""The documents the old todos engine wrote, built by hand for the migration journey.

The tracked-todo tools, the old Inbox desk and the tracked-todo engine that wrote these
are gone, so their shapes are frozen here: every field, its type, and the activity lines
each step appended. legacy_snapshot.json holds what the old code itself wrote for the same
steps (recorded at 9380571eba), and test_legacy_todos_builder keeps this builder equal to
it once both are normalized: ids, uuids and timestamps become placeholders, so what is
compared is every key, every value that is not an id or a time, and which ids point where.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import re
from typing import Any
from uuid import uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.tasks.notes import CANVAS_TEMPLATE

Db = AsyncIOMotorDatabase[dict[str, Any]]

#: The collections the old engine wrote for a todo, and how each is read back to compare.
SNAPSHOT_COLLECTIONS = ("todos", "approval_ledger", "conversations")
#: The fields of a todo's chat the migration reads; the rest is the conversation runtime's.
CONVERSATION_FIELDS = (
    "conversation_id",
    "createdAt",
    "description",
    "source",
    "todo_id",
    "user_id",
)

_TRACKED = "gaia-tracked"
_DESK_TITLE = "Inbox desk"
_DESK_CRON = "0 8 * * *"
_DESK_HOUR = 8
_DESK_DESCRIPTION = (
    "Goes through every inbox each morning: opens a sub-todo for each thread that needs you, "
    "drafts replies and briefs you, while each thread it tracks tells you what cannot wait."
)
_DESK_STANDING_RULE = (
    "deliver every briefing that has content whole, every section, never shortened or "
    "held back as routine"
)
_DESK_OBSERVATIONS = """# Observations
<!-- the evidence behind what the desk learned from the user's mail, kept across runs; the user's own instructions go in canvas.md Standing rules -->
<!-- one block per pattern, under its section:
### <sender address, recurring item or person>
- conclusion: <what it is>; <treatment, e.g. low priority, count only>
- confidence: low|medium|high
- first seen: <YYYY-MM-DD>
- last seen: <YYYY-MM-DD>
- daily counts: <YYYY-MM-DD>:<n>, ... (the 14 most recent days)
- earlier: ~<average>/day over <n> days
- suggested: <YYYY-MM-DD the briefing suggested a Gmail change from it, if ever>
-->

## Senders
<!-- one block per sender address, from the sweep's counts -->

## Recurring
<!-- mail on a cadence, e.g. a statement monthly around the 1st -->

## People
<!-- people who matter to the user, from how the user engages with them -->
"""
#: How long a todo handed over in chat waited before its first look.
_FIRST_LOOK = timedelta(hours=1)
_QUESTION_CHECK = timedelta(days=1)
_SUBTASKS_CHECK = timedelta(days=3)
_UNPLANNED_CHECK = timedelta(days=1)
#: How long a thread watch batched the thread's mail.
_THREAD_WATCH_WINDOW_SECONDS = 900
_THREAD_TRIGGERS = ("gmail_new_message", "gmail_email_sent")
_DELIVERED = "result sent as an in-app notification"


def _canvas(title: str, standing_rules: Sequence[str] = ()) -> str:
    canvas = CANVAS_TEMPLATE.format(title=title)
    heading = "## Standing rules\n"
    after_comment = canvas.index("\n", canvas.rindex(heading) + len(heading)) + 1
    rules = "".join(f"- {rule}\n" for rule in standing_rules)
    return canvas[:after_comment] + rules + canvas[after_comment:]


def _line(at: datetime, event: str, detail: str = "") -> str:
    return f"- {at.isoformat()} [{event}]" + (f" {detail}" if detail else "")


def _next_desk_morning(after: datetime) -> datetime:
    morning = after.replace(hour=_DESK_HOUR, minute=0, second=0, microsecond=0)
    return morning if morning > after else morning + timedelta(days=1)


@dataclass
class _Run:
    """One run of a todo through the old engine: its chat, its id and when it went."""

    conversation_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = field(default_factory=lambda: str(uuid4()))
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def by(self) -> str:
        return f"by GAIA in conversation {self.conversation_id[:8]}"

    def started(self) -> str:
        return _line(
            self.at, "run_started", f"scheduled run (conversation {self.conversation_id[:8]})"
        )

    def finished(self, summary: str) -> str:
        return _line(
            self.at, "run_finished", f"run {self.run_id}: {_DELIVERED} (summary={summary!r})"
        )


class LegacyTodos:
    """One user's todos as the old engine left them, written straight to Mongo."""

    def __init__(self, db: Db, user_id: str) -> None:
        self._db = db
        self._user_id = user_id
        #: The todos service filed every todo in the user's Inbox project.
        self._project_id = str(ObjectId())

    async def tracked_todo(
        self,
        title: str,
        *,
        parent: tuple[str, _Run] | None = None,
        notify: bool = True,
    ) -> str:
        """Write a todo GAIA took on with create_tracked_todo: waiting on time, first look in an hour.

        parent is the todo a run filed it under, and that run.
        """
        now = datetime.now(UTC)
        todo_id = ObjectId()
        origin, by = (
            ("", "by GAIA")
            if parent is None
            else (
                f"from conversation {parent[1].conversation_id[:8]}",
                parent[1].by,
            )
        )
        first_look = now + _FIRST_LOOK
        row: dict[str, Any] = {
            "_id": todo_id,
            "user_id": self._user_id,
            "title": title,
            "activity_content": "\n".join(
                [
                    _line(now, "created", origin),
                    _line(now, "scheduled", f"run at {first_look.isoformat()}, {by}"),
                    _line(now, "waiting_changed", f"waiting on time, {by}"),
                ]
            ),
            "canvas_content": _canvas(title),
            "completed": False,
            "created_at": now,
            "default_action": None,
            "gaia_retry_count": 0,
            "hold_checks": 0,
            "if_no_reply": None,
            "labels": [_TRACKED],
            "log_content": f"# System Log: {title}\n",
            "notify_on_run": notify,
            "priority": "none",
            "project_id": self._project_id,
            "question": None,
            "reasks_used": 0,
            "references": [],
            "scheduled_at": first_look,
            "source_conversation_id": None if parent is None else parent[1].conversation_id,
            "subtasks": [],
            "trigger_subscriptions": [],
            "updated_at": now,
            "vfs_path": f"/workspace/gaia-tasks/{todo_id}",
            "waiting_on": "time",
            "workflow_activated": True,
        }
        if parent is not None:
            row["parent_todo_id"] = parent[0]
        await self._db["todos"].insert_one(row)
        return str(todo_id)

    async def asked(self, todo_id: str, question: str, if_no_reply: str) -> None:
        """Write a run that asked the user question and waits on them, holding as if_no_reply says."""
        run = await self._ran(todo_id)
        check = run.at + _QUESTION_CHECK
        await self._finish(
            todo_id,
            [
                run.started(),
                _line(run.at, "scheduled", f"run at {check.isoformat()}, {run.by}"),
                _line(
                    run.at,
                    "waiting_changed",
                    f'waiting on user, asked "{question}", if no reply: {if_no_reply}, {run.by}',
                ),
                run.finished(question),
            ],
            {
                "waiting_on": "user",
                "question": question,
                "if_no_reply": if_no_reply,
                "scheduled_at": check,
            },
        )

    async def split(self, todo_id: str, titles: Sequence[str], report: str) -> list[str]:
        """Write a run that opened a sub-todo per title and waits on them; returns their ids."""
        run = await self._ran(todo_id)
        children = [
            await self.tracked_todo(title, parent=(todo_id, run), notify=False) for title in titles
        ]
        check = run.at + _SUBTASKS_CHECK
        await self._finish(
            todo_id,
            [
                run.started(),
                _line(run.at, "scheduled", f"run at {check.isoformat()}, {run.by}"),
                _line(run.at, "waiting_changed", f"waiting on sub_todos, {run.by}"),
                run.finished(report),
            ],
            {"waiting_on": "sub_todos", "scheduled_at": check},
        )
        return children

    async def finished(self, todo_id: str, summary: str) -> None:
        """Write a run that closed the todo with summary."""
        run = await self._ran(todo_id)
        await self._finish(
            todo_id,
            [run.started(), _line(run.at, "completed", summary), run.finished(summary)],
            {"completed": True, "completed_at": run.at},
        )

    async def watches_emails_from(self, todo_id: str, sender: str) -> None:
        """GAIA subscribed the todo to new mail from sender (subscribe_todo_to_trigger)."""
        now = datetime.now(UTC)
        watch = _subscription(
            "gmail_new_message",
            {"field_name": "sender", "operator": "contains", "value": sender},
            account_id=None,
            cooldown_seconds=0,
        )
        await self._push(todo_id, [watch], [_watch_line(now, "gmail_new_message")])

    async def inbox_desk(self) -> str:
        """Write the desk the old provisioner opened on Gmail connect, armed for the next morning."""
        now = datetime.now(UTC)
        first_run = _next_desk_morning(now)
        desk_id = ObjectId()
        await self._db["todos"].insert_one(
            {
                "_id": desk_id,
                "user_id": self._user_id,
                "title": _DESK_TITLE,
                "activity_content": "\n".join(
                    [
                        _line(now, "created"),
                        _line(now, "scheduled", f"run at {first_run.isoformat()}, by GAIA"),
                        _line(now, "recurrence_changed", f"repeats {_DESK_CRON}, by GAIA"),
                    ]
                ),
                "canvas_content": _canvas(_DESK_TITLE, [_DESK_STANDING_RULE]),
                "completed": False,
                "created_at": now,
                "default_action": None,
                "description": _DESK_DESCRIPTION,
                "external_ref": {"source": "inbox_desk", "id": "gmail"},
                "gaia_retry_count": 0,
                "hold_checks": 0,
                "if_no_reply": None,
                "labels": [_TRACKED],
                "log_content": f"# System Log: {_DESK_TITLE}\n",
                "notify_on_run": True,
                "observations_content": _DESK_OBSERVATIONS,
                "priority": "none",
                "project_id": self._project_id,
                "question": None,
                "reasks_used": 0,
                "recurrence": _DESK_CRON,
                "references": [],
                "scheduled_at": first_run,
                "source_conversation_id": None,
                "subtasks": [],
                "trigger_subscriptions": [],
                "updated_at": now,
                "vfs_path": f"/workspace/gaia-tasks/{desk_id}",
                "waiting_on": None,
                "workflow_activated": True,
            }
        )
        return str(desk_id)

    async def desk_opened_reply_task(
        self, desk_id: str, thread_id: str, title: str, *, account_id: str, report: str
    ) -> str:
        """Write a desk run that opened a watching sub-todo for a thread; returns its id."""
        desk = await self._todo(desk_id)
        run = _Run(at=desk["scheduled_at"].replace(tzinfo=UTC))
        await self._open_chat(desk_id, desk["title"], run)
        reply = await self.tracked_todo(title, parent=(desk_id, run))
        watches = [
            _subscription(
                trigger,
                {"field_name": "thread_id", "operator": "equals", "value": thread_id},
                account_id=account_id,
                cooldown_seconds=_THREAD_WATCH_WINDOW_SECONDS,
            )
            for trigger in _THREAD_TRIGGERS
        ]
        await self._db["todos"].update_one(
            {"_id": ObjectId(reply)},
            {
                "$set": {
                    "external_ref": {
                        "source": "gmail_thread",
                        "id": thread_id,
                        "account": account_id,
                    }
                }
            },
        )
        await self._push(
            reply, watches, [_watch_line(run.at, trigger) for trigger in _THREAD_TRIGGERS]
        )
        next_run = run.at + timedelta(days=1)
        await self._finish(
            desk_id,
            [
                run.started(),
                run.finished(report),
                _line(run.at, "scheduled", f"next run {next_run.isoformat()} ({_DESK_CRON})"),
            ],
            {"scheduled_at": next_run},
        )
        return reply

    async def completed_by_the_user(self, todo_id: str) -> None:
        """Write the user ticking the todo off in the app, as a stopped desk was."""
        now = datetime.now(UTC)
        await self._finish(
            todo_id,
            [_line(now, "completed", "Completed via UI")],
            {"completed": True, "completed_at": now},
        )

    async def parked_on_approval(
        self, todo_id: str, *, tool_name: str, summary: str, args: Mapping[str, object]
    ) -> str:
        """Write a run that asked approval for tool_name and ended with no next step; returns its id."""
        run = await self._ran(todo_id)
        check = run.at + _UNPLANNED_CHECK
        approval_id = f"ap_{uuid4().hex[:12]}"
        await self._db["approval_ledger"].insert_one(
            {
                "user_id": self._user_id,
                "approval_id": approval_id,
                "account": None,
                "action": None,
                "args": dict(args),
                "conversation_id": run.conversation_id,
                "created_at": run.at,
                "decided_at": None,
                "decided_by": None,
                "delivering_since": None,
                "executing_started_at": None,
                "feedback": None,
                "fingerprint": uuid4().hex,
                "outcome": None,
                "owner_agent": f"executor_{run.conversation_id}",
                "owner_id": todo_id,
                "owner_run_type": "todo",
                "owner_task_id": None,
                "preview": json.dumps(dict(args)),
                "proposing_run_id": str(uuid4()),
                "summary": summary,
                "task_id": str(uuid4()),
                "tool_key": tool_name,
                "tool_name": tool_name,
                "v": 0,
            }
        )
        await self._finish(
            todo_id,
            [
                run.started(),
                _line(
                    run.at,
                    "open_state_repaired",
                    "the run ended with no next step even after being sent back, so GAIA "
                    f"parked it as unplanned with a check at {check.isoformat()}",
                ),
            ],
            {"waiting_on": "unplanned", "scheduled_at": check},
        )
        return approval_id

    async def _todo(self, todo_id: str) -> dict[str, Any]:
        row = await self._db["todos"].find_one({"_id": ObjectId(todo_id)})
        assert row is not None, f"no legacy todo {todo_id}"
        return row

    async def _ran(self, todo_id: str) -> _Run:
        """Open the chat a run of the todo worked in, as its first run did."""
        run = _Run(at=datetime.now(UTC) + _FIRST_LOOK)
        await self._open_chat(todo_id, (await self._todo(todo_id))["title"], run)
        return run

    async def _open_chat(self, todo_id: str, title: str, run: _Run) -> None:
        await self._db["conversations"].insert_one(
            {
                "conversation_id": run.conversation_id,
                "user_id": self._user_id,
                "todo_id": todo_id,
                "description": title,
                "source": "background",
                "createdAt": run.at.isoformat(),
                "updatedAt": run.at,
                "artifacts": [],
                "is_onboarding_demo": False,
                "is_system_generated": False,
                "is_unread": False,
            }
        )

    async def _finish(self, todo_id: str, lines: list[str], fields: dict[str, Any]) -> None:
        todo = await self._todo(todo_id)
        await self._db["todos"].update_one(
            {"_id": ObjectId(todo_id)},
            {
                "$set": {
                    **fields,
                    "activity_content": "\n".join([todo["activity_content"], *lines]),
                    "updated_at": datetime.now(UTC),
                }
            },
        )

    async def _push(
        self, todo_id: str, subscriptions: list[dict[str, Any]], lines: list[str]
    ) -> None:
        todo = await self._todo(todo_id)
        await self._db["todos"].update_one(
            {"_id": ObjectId(todo_id)},
            {
                "$push": {"trigger_subscriptions": {"$each": subscriptions}},
                "$set": {
                    "activity_content": "\n".join([todo["activity_content"], *lines]),
                    "updated_at": datetime.now(UTC),
                },
            },
        )


def _subscription(
    trigger_name: str,
    condition: dict[str, str],
    *,
    account_id: str | None,
    cooldown_seconds: int,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "trigger_name": trigger_name,
        "account_id": account_id,
        "action": "execute",
        "composio_trigger_ids": [],
        "conditions": [condition],
        "cooldown_seconds": cooldown_seconds,
        "created_at": datetime.now(UTC),
        "gate": None,
        "match": "all",
        "resolution": "account",
        "status": "active",
        "trigger_data": {},
    }


def _watch_line(at: datetime, trigger_name: str) -> str:
    return _line(at, "watch_added", f"watching {trigger_name} (1 condition(s)) to execute")


# Normalizing: what two writes of the same steps share once ids and times are set aside.

_ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)?")
_UUID = re.compile(
    r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
)
_OBJECT_ID = re.compile(r"\b[0-9a-f]{24}\b")
_HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
_APPROVAL_ID = re.compile(r"\bap_[0-9a-f]{12}\b")
_ACCOUNT_ID = re.compile(r"\bacct_[0-9a-f]{16}\b")
#: A chat named by the first 8 characters of its id, as activity lines name it.
_SHORT_ID = re.compile(r"\b[0-9a-f]{8}\b")
_SORT_KEYS = {"todos": "title", "approval_ledger": "tool_name", "conversations": "description"}


class _Placeholders:
    """Give each id one placeholder, in the order ids are first seen, so references still line up."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def __call__(self, kind: str, key: str) -> str:
        return self._seen.setdefault(f"{kind}:{key}", f"<{kind}:{len(self._seen)}>")

    def text(self, value: str) -> str:
        value = _ISO_TIME.sub("<time>", value)
        value = _UUID.sub(lambda m: self("id", m[0][:8]), value)
        value = _OBJECT_ID.sub(lambda m: self("oid", m[0]), value)
        value = _HEX32.sub(lambda m: self("hash", m[0]), value)
        value = _APPROVAL_ID.sub(lambda m: self("approval", m[0]), value)
        value = _ACCOUNT_ID.sub(lambda m: self("account", m[0]), value)
        return _SHORT_ID.sub(lambda m: self("id", m[0]), value)

    def value(self, value: object) -> object:
        if isinstance(value, datetime):
            return "<time>"
        if isinstance(value, ObjectId):
            return self("oid", str(value))
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {k: self.value(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [self.value(v) for v in value]
        return value


async def normalized_legacy(db: Db, user_id: str) -> dict[str, list[object]]:
    """Read back the user's legacy documents with every id and time replaced by a placeholder."""
    names = _Placeholders()
    shot: dict[str, list[object]] = {}
    for collection in SNAPSHOT_COLLECTIONS:
        projection: dict[str, int] | None = (
            dict.fromkeys(CONVERSATION_FIELDS, 1) | {"_id": 0}
            if collection == "conversations"
            else {"_id": 0}
            if collection == "approval_ledger"
            else None
        )
        rows = await db[collection].find({"user_id": user_id}, projection).to_list(None)
        if collection == "conversations":
            rows = [row for row in rows if "todo_id" in row]
        rows.sort(key=lambda row: str(row[_SORT_KEYS[collection]]))
        shot[collection] = [names.value(row) for row in rows]
    return shot
