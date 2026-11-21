"""Prove the tasks collections hold exactly what todos and workflows held.

Written apart from the migration on purpose: every check reads the source document and
the stored target and compares fields one by one, so a mistake in the migration's mapping
shows up here instead of being repeated. The intentional transforms are the ones listed
in TRANSFORMS; anything else that differs is a diff naming the document and the field.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from scripts.tasks_migration.legacy import (
    GAIA_TRACKED_LABEL,
    LABEL_FLAGS,
    ONBOARDING_LABEL,
    LegacyPlaybook,
    LegacyTodo,
    LegacyWorkflow,
    legacy_playbook_valid,
    with_stable_defaults,
)
from scripts.tasks_migration.migrate import (
    LEGACY_TRIGGER_CONDITION,
    LEGACY_WAITERS,
    TASK_TRIGGER_CONDITION,
    TASK_WAITER,
    WORKFLOW_CHAT_PURPOSE,
)
from scripts.tasks_migration.transform import owed_nudge

from app.constants.tasks import INBOX_DESK_SYSTEM_KEY, TASK_ID_PATTERN, TaskRunKind
from app.models.playbook_models import PlaybookBody
from app.models.todo_models import SubTask
from app.models.trigger_subscription_models import TriggerSubscription
from app.services.tasks.body_hash import task_body_hash

Document = dict[str, Any]

#: Every field that changes on the way, and how; a difference not named here is a diff.
TRANSFORMS: Final = (
    "todo labels: gaia-tracked becomes assignee gaia, onboarding becomes from_onboarding, the "
    "six engine labels become status_flags, user labels and needs-follow-up are dropped",
    "todo due_date/recurrence/scheduled_at become when (date, repeat) and next_check_at",
    "an open plain todo due ahead owes its nudge at its due time (nudge_at)",
    "todo waiting_on/question/if_no_reply/default_action/hold_checks become waiting",
    "todo subtasks and subscriptions stored without created_at, id or status get the todo's "
    "creation time, a position-derived id and active, so every run maps them the same way",
    "todo activity_content becomes task_runs records whose slices join back to it",
    "workflow prompt (or description when empty) becomes body; description becomes the template summary",
    "workflow trigger_config + gate become when and one subscription; trigger_config.enabled "
    "and its unread extra keys are dropped (liveness is active)",
    "workflow status scheduled/executing/completed becomes run_state idle/running/ended",
    "workflow deactivated_reason is kept only while it is off",
    "dropped: project_id, workflow_id, workflow_activated, vfs_path, steps, "
    "current_step_index, execution_logs, error_message, is_public, is_explore, slug, created_by",
    "playbook workflow_hash becomes body_hash: the body's hash when it was valid, kept when stale",
)


@dataclass(frozen=True)
class Diff:
    collection: str
    doc_id: str
    field: str
    expected: object
    actual: object

    def line(self) -> str:
        return (
            f"{self.collection}/{self.doc_id} {self.field}: "
            f"expected {self.expected!r}, found {self.actual!r}"
        )


@dataclass
class ParityReport:
    diffs: list[Diff] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)

    @property
    def clean(self) -> bool:
        return not self.diffs

    def summary(self) -> str:
        lines = ["tasks parity"]
        lines += [f"  {name}: {count}" for name, count in sorted(self.counts.items())]
        lines += [f"  DIFF {diff.line()}" for diff in self.diffs]
        lines.append("clean" if self.clean else f"{len(self.diffs)} difference(s)")
        return "\n".join(lines)


def _norm(value: object) -> object:
    """A stored value in comparable form: aware UTC datetimes to the millisecond, ids as text."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).replace(microsecond=aware.microsecond // 1000 * 1000)
    if isinstance(value, str) and len(value) > 18 and value[4:5] == "-" and value[10:11] == "T":
        try:
            return _norm(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return value
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Mapping):
        return {k: _norm(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def _get(doc: Mapping[str, object], path: str, default: object = None) -> object:
    node: object = doc
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return default if node is None else node


class _Checker:
    def __init__(self, report: ParityReport) -> None:
        self.report = report

    def eq(
        self, collection: str, doc_id: object, name: str, expected: object, actual: object
    ) -> None:
        if _norm(expected) != _norm(actual):
            self.report.diffs.append(Diff(collection, str(doc_id), name, expected, actual))

    def fail(self, collection: str, doc_id: object, name: str, why: str) -> None:
        self.report.diffs.append(Diff(collection, str(doc_id), name, why, None))


_BODY_FIELDS: Final = ("description", "steps", "result_brief")


def _playbook_body(raw: Mapping[str, object]) -> object:
    """The authored part of a stored playbook, as the replay reads it; None when it does not parse."""
    try:
        body = PlaybookBody.model_validate({name: raw.get(name) for name in _BODY_FIELDS})
    except ValueError:
        return None
    return body.model_dump(mode="json")


def _subtasks(raw: object) -> list[Document]:
    return (
        [SubTask.model_validate(sub).model_dump() for sub in raw] if isinstance(raw, list) else []
    )


def _subscriptions(raw: Iterable[Mapping[str, object]]) -> list[Document]:
    return [TriggerSubscription.model_validate(sub).model_dump() for sub in raw]


@dataclass
class _Data:
    todos: dict[str, Document]
    workflows: dict[str, Document]
    executions: list[Document]
    playbooks: list[Document]
    conversations: list[Document]
    approvals: list[Document]
    waits: list[Document]
    tasks: dict[str, Document]
    runs: list[Document]
    templates: dict[str, Document]
    task_playbooks: dict[str, Document]


async def _load(db: AsyncIOMotorDatabase[Document], scope: Document) -> _Data:
    async def rows(name: str, projection: Document | None = None) -> list[Document]:
        return [raw async for raw in db[name].find(scope, projection)]

    chat_fields = {
        "todo_id": 1,
        "task_id": 1,
        "metadata.workflow_id": 1,
        "system_purpose": 1,
        "createdAt": 1,
        "user_id": 1,
        "conversation_id": 1,
    }
    template_ids = {raw["_id"] for raw in await rows("workflows", {"_id": 1})}
    return _Data(
        todos={str(raw["_id"]): with_stable_defaults(raw) for raw in await rows("todos")},
        workflows={raw["_id"]: raw for raw in await rows("workflows")},
        executions=await rows("workflow_executions"),
        playbooks=await rows("playbooks"),
        conversations=await rows("conversations", chat_fields),
        approvals=await rows("approval_ledger"),
        waits=await rows("waits"),
        tasks={raw["_id"]: raw for raw in await rows("tasks")},
        runs=await rows("task_runs"),
        templates={
            raw["_id"]: raw
            async for raw in db["task_templates"].find({"_id": {"$in": sorted(template_ids)}})
        },
        task_playbooks={raw["playbook_id"]: raw for raw in await rows("task_playbooks")},
    )


def _newest_desks(todos: Mapping[str, Document]) -> set[str]:
    newest: dict[str, tuple[datetime, str]] = {}
    for todo_id, raw in todos.items():
        if _get(raw, "external_ref.source") != "inbox_desk":
            continue
        made = _norm(raw.get("created_at") or ObjectId(todo_id).generation_time)
        assert isinstance(made, datetime)
        if raw["user_id"] not in newest or made > newest[raw["user_id"]][0]:
            newest[raw["user_id"]] = (made, todo_id)
    return {todo_id for _, todo_id in newest.values()}


def _check_todo(check: _Checker, todo_id: str, todo: Document, task: Document, desk: bool) -> None:
    c = "tasks"
    labels: list[str] = list(todo.get("labels") or [])
    gaia = GAIA_TRACKED_LABEL in labels
    pairs = {
        "user_id": (todo["user_id"], task.get("user_id")),
        "title": (todo["title"], task.get("title")),
        "body": (todo.get("description") or "", task.get("body", "")),
        "assignee": ("gaia" if gaia else "user", task.get("assignee")),
        "priority": (todo.get("priority") or "none", task.get("priority", "none")),
        "completed": (bool(todo.get("completed")), task.get("completed", False)),
        "completed_at": (todo.get("completed_at"), task.get("completed_at")),
        "subtasks": (_subtasks(todo.get("subtasks")), _subtasks(task.get("subtasks"))),
        "parent_id": (todo.get("parent_todo_id"), task.get("parent_id")),
        "retry_count": (todo.get("gaia_retry_count") or 0, task.get("retry_count", 0)),
        "expires_at": (todo.get("expires_at"), task.get("expires_at")),
        "references": (todo.get("references") or [], task.get("references") or []),
        "notify": (todo.get("notify_on_run", True), task.get("notify", True)),
        "pause_reason": (todo.get("pause_reason"), task.get("pause_reason")),
        "active": (todo.get("pause_reason") is None, task.get("active", True)),
        "reasks_used": (todo.get("reasks_used") or 0, task.get("reasks_used", 0)),
        "notes": (todo.get("canvas_content"), task.get("notes")),
        "observations": (todo.get("observations_content"), task.get("observations")),
        "log": (todo.get("log_content"), task.get("log")),
        "source_email": (todo.get("source_email"), task.get("source_email")),
        "source_conversation_id": (
            todo.get("source_conversation_id"),
            task.get("source_conversation_id"),
        ),
        "external_ref": (todo.get("external_ref"), task.get("external_ref")),
        "created_at": (todo.get("created_at"), task.get("created_at")),
        "updated_at": (todo.get("updated_at"), task.get("updated_at")),
        "status_flags": (
            list(
                dict.fromkeys(LABEL_FLAGS[label].value for label in labels if label in LABEL_FLAGS)
            ),
            task.get("status_flags") or [],
        ),
        "from_onboarding": (ONBOARDING_LABEL in labels, task.get("from_onboarding", False)),
        "subscriptions": (
            _subscriptions(todo.get("trigger_subscriptions") or []),
            _subscriptions(task.get("subscriptions") or []),
        ),
        "system_key": (INBOX_DESK_SYSTEM_KEY if desk else None, task.get("system_key")),
    }
    for name, (expected, actual) in pairs.items():
        check.eq(c, todo_id, name, expected, actual)
    _check_todo_when(check, todo_id, todo, task, gaia=gaia)
    _check_todo_waiting(check, todo_id, todo, task)


def _check_todo_when(
    check: _Checker, todo_id: str, todo: Document, task: Document, *, gaia: bool
) -> None:
    c, when = "tasks", task.get("when") or {}
    recurrence, due, scheduled = (
        todo.get("recurrence"),
        todo.get("due_date"),
        todo.get("scheduled_at"),
    )
    if recurrence:
        check.eq(c, todo_id, "when.kind", "repeat", when.get("kind"))
        check.eq(c, todo_id, "when.rule", recurrence, when.get("rule"))
        check.eq(c, todo_id, "when.next_run", scheduled if gaia else due, when.get("next_run"))
        check.eq(c, todo_id, "next_check_at", None, task.get("next_check_at"))
        return
    kind = "date" if due else ("event" if todo.get("trigger_subscriptions") else "none")
    check.eq(c, todo_id, "when.kind", kind, when.get("kind"))
    check.eq(c, todo_id, "when.at", due, when.get("at"))
    check.eq(
        c,
        todo_id,
        "when.timezone",
        todo.get("due_date_timezone") if due else None,
        when.get("timezone"),
    )
    check.eq(c, todo_id, "next_check_at", scheduled, task.get("next_check_at"))
    owed = owed_nudge(LegacyTodo.model_validate(todo), now=datetime.now(UTC))
    check.eq(c, todo_id, "nudge_at", owed, task.get("nudge_at"))


def _check_todo_waiting(check: _Checker, todo_id: str, todo: Document, task: Document) -> None:
    c, waiting = "tasks", task.get("waiting") or {}
    question = waiting.get("question") or {}
    check.eq(c, todo_id, "waiting.on", todo.get("waiting_on"), waiting.get("on"))
    check.eq(c, todo_id, "waiting.question.text", todo.get("question"), question.get("text"))
    check.eq(
        c,
        todo_id,
        "waiting.question.if_no_reply",
        todo.get("if_no_reply"),
        question.get("if_no_reply"),
    )
    check.eq(
        c,
        todo_id,
        "waiting.question.default_action",
        todo.get("default_action"),
        question.get("default_action"),
    )
    check.eq(
        c,
        todo_id,
        "waiting.question.hold_checks",
        todo.get("hold_checks") or 0,
        question.get("hold_checks", 0),
    )


_RUN_STATE = {"scheduled": "idle", "executing": "running", "completed": "ended"}


def _check_workflow(
    check: _Checker, wf_id: str, wf: Document, task: Document, parent: str | None
) -> None:
    c, trigger = "tasks", wf.get("trigger_config") or {}
    activated = wf.get("activated", True)
    pairs = {
        "user_id": (wf["user_id"], task.get("user_id")),
        "title": (wf["title"], task.get("title")),
        "body": (wf.get("prompt") or wf.get("description") or "", task.get("body", "")),
        "assignee": ("gaia", task.get("assignee")),
        "parent_id": (parent, task.get("parent_id")),
        "active": (activated, task.get("active", True)),
        "pause_reason": (
            None if activated else wf.get("deactivated_reason"),
            task.get("pause_reason"),
        ),
        "run_state": (
            _RUN_STATE.get(wf.get("status") or "scheduled"),
            task.get("run_state", "idle"),
        ),
        "notify": (wf.get("notify_on_completion", True), task.get("notify", True)),
        "icon": (wf.get("icon"), task.get("icon")),
        "icon_color": (wf.get("icon_color"), task.get("icon_color")),
        "integration_ids": (wf.get("integration_ids") or [], task.get("integration_ids") or []),
        "blocked_on_integrations": (
            wf.get("blocked_on_integrations") or [],
            task.get("blocked_on_integrations") or [],
        ),
        "max_occurrences": (wf.get("max_occurrences"), task.get("max_occurrences")),
        "stop_after": (wf.get("stop_after"), task.get("stop_after")),
        "occurrence_count": (wf.get("occurrence_count") or 0, task.get("occurrence_count", 0)),
        "total_runs": (wf.get("total_executions") or 0, task.get("total_runs", 0)),
        "successful_runs": (wf.get("successful_executions") or 0, task.get("successful_runs", 0)),
        "last_run_at": (wf.get("last_executed_at"), task.get("last_run_at")),
        "last_playbook_discard": (
            wf.get("last_playbook_discard"),
            task.get("last_playbook_discard"),
        ),
        "system_key": (
            wf.get("system_workflow_key") if wf.get("is_system_workflow") else None,
            task.get("system_key"),
        ),
        "source_integration": (wf.get("source_integration"), task.get("source_integration")),
        "created_at": (wf.get("created_at"), task.get("created_at")),
        "updated_at": (wf.get("updated_at"), task.get("updated_at")),
    }
    for name, (expected, actual) in pairs.items():
        check.eq(c, wf_id, name, expected, actual)
    when, subs = task.get("when") or {}, task.get("subscriptions") or []
    kind = {"manual": "none", "schedule": "repeat", "integration": "event"}.get(trigger.get("type"))
    check.eq(c, wf_id, "when.kind", kind, when.get("kind"))
    if kind == "repeat":
        check.eq(c, wf_id, "when.rule", trigger.get("cron_expression"), when.get("rule"))
        check.eq(c, wf_id, "when.timezone", trigger.get("timezone"), when.get("timezone"))
        check.eq(c, wf_id, "when.next_run", trigger.get("next_run"), when.get("next_run"))
    if kind != "event":
        check.eq(c, wf_id, "subscriptions", [], subs)
        return
    if len(subs) != 1:
        check.fail(c, wf_id, "subscriptions", f"one subscription, found {len(subs)}")
        return
    (sub,) = subs
    check.eq(
        c, wf_id, "subscription.trigger_name", trigger.get("trigger_name"), sub.get("trigger_name")
    )
    check.eq(
        c,
        wf_id,
        "subscription.composio_trigger_ids",
        trigger.get("composio_trigger_ids") or [],
        sub.get("composio_trigger_ids") or [],
    )
    check.eq(
        c,
        wf_id,
        "subscription.trigger_data",
        trigger.get("trigger_data") or {},
        sub.get("trigger_data") or {},
    )
    check.eq(c, wf_id, "subscription.gate", wf.get("gate"), sub.get("gate"))
    check.eq(c, wf_id, "subscription.action", "execute", sub.get("action"))


def _check_sources(check: _Checker, data: _Data) -> tuple[set[str], Counter[tuple[str, str]]]:
    """Check every todo and workflow against its task; return the ids expected and counts per user."""
    desks = _newest_desks(data.todos)
    expected_ids: set[str] = set()
    per_user: Counter[tuple[str, str]] = Counter()
    for todo_id, todo in data.todos.items():
        expected_ids.add(todo_id)
        gaia = GAIA_TRACKED_LABEL in (todo.get("labels") or [])
        per_user[(todo["user_id"], "gaia" if gaia else "user")] += 1
        task = data.tasks.get(todo_id)
        if task is None:
            check.fail("tasks", todo_id, "_id", "a task for this todo")
            continue
        _check_todo(check, todo_id, todo, task, todo_id in desks)
    linking = {
        raw["workflow_id"]: tid
        for tid, raw in data.todos.items()
        if isinstance(raw.get("workflow_id"), str)
    }
    for wf_id, wf in data.workflows.items():
        if wf.get("is_explore"):
            continue
        if wf_id in expected_ids:
            check.fail("tasks", wf_id, "_id", "a workflow id that no todo also holds")
        expected_ids.add(wf_id)
        per_user[(wf["user_id"], "gaia")] += 1
        task = data.tasks.get(wf_id)
        if task is None:
            check.fail("tasks", wf_id, "_id", "a task for this workflow")
            continue
        parent = None
        if wf.get("is_todo_workflow"):
            source = wf.get("source_todo_id")
            parent = source if source in data.todos else linking.get(wf_id)
        _check_workflow(check, wf_id, wf, task, parent)
    return expected_ids, per_user


def _check_stored_task(check: _Checker, data: _Data, task_id: str, task: Document) -> None:
    """Check what holds of every stored task: its id, its parent, and an armed schedule."""
    if not TASK_ID_PATTERN.fullmatch(task_id):
        check.fail("tasks", task_id, "_id", "an id a task may carry")
    parent = task.get("parent_id")
    if parent is not None and (data.tasks.get(parent) or {}).get("user_id") != task["user_id"]:
        check.fail("tasks", task_id, "parent_id", f"a task of the same user, not {parent!r}")
    when = task.get("when") or {}
    armed = (
        task.get("assignee") == "gaia" and task.get("active", True) and not task.get("completed")
    )
    if armed and when.get("kind") == "repeat" and when.get("next_run") is None:
        check.fail("tasks", task_id, "when.next_run", "a next run on an active schedule")


def _check_tasks(check: _Checker, data: _Data) -> None:
    expected_ids, per_user = _check_sources(check, data)
    stored = Counter((t["user_id"], t.get("assignee")) for t in data.tasks.values())
    for key in set(per_user) | set(stored):
        check.eq("tasks", f"{key[0]}:{key[1]}", "count", per_user[key], stored[key])
    for task_id, task in data.tasks.items():
        if task_id not in expected_ids:
            check.fail("tasks", task_id, "_id", "no task without a todo or workflow behind it")
        _check_stored_task(check, data, task_id, task)
    check.report.counts["tasks"] = len(data.tasks)


def _check_templates(check: _Checker, data: _Data) -> None:
    listed = {
        wf_id: wf
        for wf_id, wf in data.workflows.items()
        if wf.get("is_public") or wf.get("is_explore")
    }
    for wf_id, wf in listed.items():
        template = data.templates.get(wf_id)
        if template is None:
            check.fail("task_templates", wf_id, "_id", "a template for this public workflow")
            continue
        curated = bool(wf.get("is_explore"))
        pairs = {
            "title": (wf["title"], template.get("title")),
            "body": (wf.get("prompt") or wf.get("description") or "", template.get("body")),
            "summary": (wf.get("description") or "", template.get("summary", "")),
            "origin": ("curated" if curated else "community", template.get("origin")),
            "creator_id": (wf.get("created_by") or wf["user_id"], template.get("creator_id")),
            "source_task_id": (None if curated else wf_id, template.get("source_task_id")),
            "run_count": (wf.get("total_executions") or 0, template.get("run_count", 0)),
            "integration_ids": (
                wf.get("integration_ids") or [],
                template.get("integration_ids") or [],
            ),
        }
        if wf.get("slug"):
            pairs["slug"] = (wf["slug"], template.get("slug"))
        for name, (expected, actual) in pairs.items():
            check.eq("task_templates", wf_id, name, expected, actual)
    by_slug = {t.get("slug"): t_id for t_id, t in data.templates.items()}
    for wf_id, wf in listed.items():
        if wf.get("slug") and by_slug.get(wf["slug"]) != wf_id:
            check.fail(
                "task_templates", wf_id, "slug", f"slug {wf['slug']!r} resolving to this template"
            )
    for t_id, template in data.templates.items():
        source = template.get("source_task_id")
        if source is not None and source not in data.tasks:
            check.fail("task_templates", t_id, "source_task_id", "a task the template came from")
    check.report.counts["templates"] = len(data.templates)


def _check_runs(check: _Checker, data: _Data) -> None:
    runs = {run["run_id"]: run for run in data.runs}
    for execution in data.executions:
        if execution["workflow_id"] not in data.tasks:
            check.report.counts["executions_of_deleted_workflows"] += 1
            continue
        run = runs.get(execution["execution_id"])
        if run is None:
            check.fail("task_runs", execution["execution_id"], "run_id", "a run for this execution")
            continue
        for name, target in (
            ("workflow_id", "task_id"),
            ("user_id", "user_id"),
            ("status", "status"),
            ("started_at", "started_at"),
            ("completed_at", "completed_at"),
            ("summary", "summary"),
            ("error_message", "error_message"),
            ("conversation_id", "conversation_id"),
            ("trigger_type", "trigger_type"),
        ):
            check.eq(
                "task_runs", execution["execution_id"], target, execution.get(name), run.get(target)
            )
        check.eq(
            "task_runs",
            execution["execution_id"],
            "trace",
            execution.get("trace") or [],
            run.get("trace") or [],
        )
    slices: defaultdict[str, list[Document]] = defaultdict(list)
    for run in data.runs:
        if run["task_id"] not in data.tasks:
            check.fail("task_runs", run["run_id"], "task_id", "a task this run belongs to")
        if run.get("imported") is not None:
            slices[run["task_id"]].append(run)
    for todo_id, todo in data.todos.items():
        cut = sorted(slices.get(todo_id, []), key=lambda r: r["imported"]["seq"])
        joined = "".join(r["imported"]["text"] for r in cut)
        check.eq("task_runs", todo_id, "activity", todo.get("activity_content") or "", joined)
        for run in cut:
            history = run.get("kind") == TaskRunKind.HISTORY.value
            if history != (run.get("status") is None):
                check.fail(
                    "task_runs",
                    run["run_id"],
                    "status",
                    "a status on every run and none on history",
                )
    check.report.counts["runs"] = len(data.runs)


def _check_playbooks(check: _Checker, data: _Data) -> None:
    for raw in data.playbooks:
        wf = data.workflows.get(raw["workflow_id"])
        if wf is None or wf.get("is_explore") or wf["user_id"] != raw["user_id"]:
            check.report.counts["playbooks_of_deleted_workflows"] += 1
            continue
        stored = data.task_playbooks.get(raw["playbook_id"])
        if stored is None:
            check.fail(
                "task_playbooks", raw["playbook_id"], "playbook_id", "a playbook for this one"
            )
            continue
        legacy = LegacyPlaybook.model_validate(raw)
        workflow = LegacyWorkflow.model_validate(wf)
        task = data.tasks.get(raw["workflow_id"], {})
        check.eq(
            "task_playbooks",
            raw["playbook_id"],
            "task_id",
            raw["workflow_id"],
            stored.get("task_id"),
        )
        check.eq(
            "task_playbooks",
            raw["playbook_id"],
            "body",
            _playbook_body(raw),
            _playbook_body(stored),
        )
        for name in (
            "last_run_status",
            "suspect_streak",
            "heal_attempts",
            "revision",
            "created_at",
        ):
            check.eq("task_playbooks", raw["playbook_id"], name, raw.get(name), stored.get(name))
        valid_before = legacy_playbook_valid(legacy, workflow)
        valid_after = stored.get("body_hash") == task_body_hash(str(task.get("body", "")))
        check.eq("task_playbooks", raw["playbook_id"], "valid", valid_before, valid_after)
        check.report.counts["playbooks_valid" if valid_after else "playbooks_stale"] += 1
    for pb_id, stored in data.task_playbooks.items():
        if stored["task_id"] not in data.tasks:
            check.fail("task_playbooks", pb_id, "task_id", "a task this playbook belongs to")


def _check_conversations(check: _Checker, data: _Data) -> None:
    oldest: dict[str, Document] = {}
    bound: Counter[str] = Counter()
    for chat in data.conversations:
        task_id = chat.get("task_id")
        if task_id is not None:
            bound[task_id] += 1
            if (data.tasks.get(task_id) or {}).get("user_id") != chat["user_id"]:
                check.fail(
                    "conversations", chat["conversation_id"], "task_id", "a task of the chat's user"
                )
        todo_id = chat.get("todo_id")
        if isinstance(todo_id, str) and todo_id in data.tasks:
            check.eq("conversations", chat["conversation_id"], "task_id", todo_id, task_id)
        wf_id = _get(chat, "metadata.workflow_id")
        if chat.get("system_purpose") == WORKFLOW_CHAT_PURPOSE and wf_id in data.tasks:
            held = oldest.get(str(wf_id))
            if held is None or str(chat.get("createdAt") or "") < str(held.get("createdAt") or ""):
                oldest[str(wf_id)] = chat
    for wf_id, chat in oldest.items():
        check.eq("conversations", chat["conversation_id"], "task_id", wf_id, chat.get("task_id"))
    for task_id, count in bound.items():
        if count > 1:
            check.fail("conversations", task_id, "task_id", f"one chat per task, found {count}")
    check.report.counts["chats_bound"] = sum(bound.values())


def _check_approvals_and_waits(check: _Checker, data: _Data) -> None:
    for row in data.approvals:
        owner = row.get("owner_id")
        expected = (
            owner if row.get("owner_run_type") in LEGACY_WAITERS and owner in data.tasks else None
        )
        check.eq(
            "approval_ledger",
            row.get("approval_id"),
            "owner_task_id",
            expected,
            row.get("owner_task_id"),
        )
    keys = {
        (w["user_id"], w["condition"], w["subject_id"], w["waiter"], w["waiter_id"])
        for w in data.waits
    }
    for wait in data.waits:
        legacy_waiter = wait["waiter"] in LEGACY_WAITERS
        if not legacy_waiter and wait["condition"] != LEGACY_TRIGGER_CONDITION:
            continue
        if legacy_waiter and wait["waiter_id"] not in data.tasks:
            continue
        twin = (
            wait["user_id"],
            TASK_TRIGGER_CONDITION
            if wait["condition"] == LEGACY_TRIGGER_CONDITION
            else wait["condition"],
            wait["subject_id"],
            TASK_WAITER if legacy_waiter else wait["waiter"],
            wait["waiter_id"],
        )
        if twin not in keys:
            check.fail("waits", str(wait["_id"]), "twin", f"a wait kept as {twin}")
    for wait in data.waits:
        if wait["waiter"] == TASK_WAITER and wait["waiter_id"] not in data.tasks:
            check.fail("waits", str(wait["_id"]), "waiter_id", "a task this wait wakes")


async def check_parity(
    db: AsyncIOMotorDatabase[Document], *, user_ids: Iterable[str] | None = None
) -> ParityReport:
    """Compare every source document with its target; the report is clean only with no diff at all."""
    scope: Document = {} if user_ids is None else {"user_id": {"$in": sorted(user_ids)}}
    data = await _load(db, scope)
    report = ParityReport()
    check = _Checker(report)
    _check_tasks(check, data)
    _check_templates(check, data)
    _check_runs(check, data)
    _check_playbooks(check, data)
    _check_conversations(check, data)
    _check_approvals_and_waits(check, data)
    return report
