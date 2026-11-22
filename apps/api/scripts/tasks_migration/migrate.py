"""Move todos and workflows into tasks: idempotent, resumable, dry-run unless told to apply.

The collections the switch retires (todos, workflows, workflow_executions, playbooks) are
only read. tasks, task_runs, task_templates and task_playbooks are written whole, by id,
from their sources, so a second run writes the same documents again. The collections both
builds share are only added to, never changed: a conversation gains task_id, an approval
gains owner_task_id, and a wait on a todo or workflow gains a twin waiting as the task. The
previous build reads all three exactly as before, which is what makes a rollback safe.

Each phase records the last source id it finished in task_migration_progress, so an
interrupted run picks up there; --restart ignores it.
"""

from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, ParamSpec, TypeVar

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ValidationError
from scripts.tasks_migration.legacy import (
    LegacyExecution,
    LegacyPlaybook,
    LegacyTodo,
    LegacyWorkflow,
)
from scripts.tasks_migration.transform import (
    Unmappable,
    dropped_labels,
    playbook_for_task,
    run_from_execution,
    runs_from_activity,
    task_from_todo,
    task_from_workflow,
    template_from_workflow,
)

from app.models.task_models import TaskDocument

Document = dict[str, Any]
T = TypeVar("T")
P = ParamSpec("P")

PROGRESS: Final = "task_migration_progress"
#: Documents written between two progress marks.
BATCH_SIZE: Final = 100
#: The waiter and condition names a twin wait is kept under once it waits as a task.
TASK_WAITER: Final = "task"
LEGACY_WAITERS: Final = frozenset({"todo", "workflow"})
TASK_TRIGGER_CONDITION: Final = "task_trigger_configured"
LEGACY_TRIGGER_CONDITION: Final = "workflow_trigger_configured"
WORKFLOW_CHAT_PURPOSE: Final = "workflow_execution"


class Phase(StrEnum):
    TASKS_FROM_TODOS = "tasks_from_todos"
    TASKS_FROM_WORKFLOWS = "tasks_from_workflows"
    TEMPLATES = "templates"
    RUNS_FROM_EXECUTIONS = "runs_from_executions"
    RUNS_FROM_ACTIVITY = "runs_from_activity"
    PLAYBOOKS = "playbooks"
    CONVERSATIONS = "conversations"
    APPROVALS = "approvals"
    WAITS = "waits"


@dataclass(frozen=True)
class Problem:
    """A source document left out because the task model cannot hold it faithfully."""

    collection: str
    doc_id: str
    reason: str


@dataclass
class MigrationReport:
    applied: bool
    written: dict[Phase, int] = field(default_factory=lambda: defaultdict(int))
    #: Intentional transforms worth a count in the summary: what was dropped, and why.
    notes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    problems: list[Problem] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        mode = "APPLIED" if self.applied else "DRY RUN"
        lines = [f"[{mode}] tasks migration"]
        lines += [f"  {phase.value}: {count}" for phase, count in self.written.items()]
        lines += [f"  note {name}: {count}" for name, count in sorted(self.notes.items())]
        lines += [f"  PROBLEM {p.collection}/{p.doc_id}: {p.reason}" for p in self.problems]
        lines.append("clean" if self.clean else f"{len(self.problems)} document(s) not migrated")
        return "\n".join(lines)


@dataclass(frozen=True)
class Scope:
    """The users whose documents move; None moves every user's."""

    user_ids: frozenset[str] | None = None

    def filter(self) -> Document:
        return {} if self.user_ids is None else {"user_id": {"$in": sorted(self.user_ids)}}


@dataclass
class _Run:
    db: AsyncIOMotorDatabase[Document]
    scope: Scope
    apply: bool
    restart: bool
    report: MigrationReport
    task_ids: set[str] = field(default_factory=set)

    async def _done(self, phase: Phase) -> tuple[bool, Any]:
        if self.restart or not self.apply:
            return False, None
        mark = await self.db[PROGRESS].find_one({"_id": phase.value})
        if mark is None:
            return False, None
        return bool(mark.get("done")), mark.get("last_id")

    async def _mark(self, phase: Phase, *, last_id: object, done: bool) -> None:
        if self.apply:
            await self.db[PROGRESS].update_one(
                {"_id": phase.value}, {"$set": {"last_id": last_id, "done": done}}, upsert=True
            )

    async def source(
        self,
        phase: Phase,
        collection: str,
        *,
        projection: Document | None = None,
        resumable: bool = True,
    ) -> AsyncIterator[Document]:
        """Yield a source collection in _id order, after the last id the phase finished.

        A phase that must see every document at once (it picks one among several) is not
        resumable: it reads from the start each time, and its writes are idempotent.
        """
        sort_key = "_id"
        done, last_id = await self._done(phase) if resumable else (False, None)
        if done:
            return
        filt = self.scope.filter()
        if last_id is not None:
            filt = {**filt, sort_key: {"$gt": last_id}}
        pending = 0
        last: object = last_id
        async for raw in self.db[collection].find(filt, projection).sort(sort_key, 1):
            yield raw
            last, pending = raw[sort_key], pending + 1
            if pending >= BATCH_SIZE:
                await self._mark(phase, last_id=last, done=False)
                pending = 0
        await self._mark(phase, last_id=last, done=True)

    def problem(self, collection: str, doc_id: object, reason: str) -> None:
        self.report.problems.append(Problem(collection, str(doc_id), reason))

    async def replace(
        self, phase: Phase, collection: str, key: Document, document: Document
    ) -> None:
        self.report.written[phase] += 1
        if self.apply:
            await self.db[collection].replace_one(key, document, upsert=True)


def _task_document(task: TaskDocument) -> Document:
    return {"_id": task.id, **task.model_dump(exclude={"id"}, exclude_none=True)}


def _keyed(model: BaseModel, *, identity: str | None) -> Document:
    data = model.model_dump(exclude={"id"}, exclude_none=True)
    if identity is not None:
        data["_id"] = identity
    return data


def _mapped(
    run: _Run,
    collection: str,
    raw: Document,
    build: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T | None:
    """Build a target from a source document, recording a problem instead when it cannot be held."""
    try:
        return build(*args, **kwargs)
    except (Unmappable, ValidationError) as error:
        run.problem(collection, raw.get("_id"), str(error).splitlines()[0])
        return None


async def _desk_owners(run: _Run) -> set[str]:
    """The Inbox desk per user the provisioner reads: the newest desk document."""
    newest: dict[str, tuple[datetime, str]] = {}
    filt = {**run.scope.filter(), "external_ref.source": "inbox_desk"}
    async for raw in run.db["todos"].find(filt, {"user_id": 1, "created_at": 1}):
        made = raw.get("created_at") or raw["_id"].generation_time
        if raw["user_id"] not in newest or made > newest[raw["user_id"]][0]:
            newest[raw["user_id"]] = (made, str(raw["_id"]))
    return {todo_id for _, todo_id in newest.values()}


async def _migrate_todos(run: _Run) -> None:
    desks = await _desk_owners(run)
    async for raw in run.source(Phase.TASKS_FROM_TODOS, "todos"):
        todo = _mapped(run, "todos", raw, LegacyTodo.model_validate, raw)
        if todo is None:
            continue
        task = _mapped(run, "todos", raw, task_from_todo, todo, is_users_desk=todo.id in desks)
        if task is None:
            continue
        run.report.notes["labels_dropped"] += len(dropped_labels(todo.labels))
        await run.replace(Phase.TASKS_FROM_TODOS, "tasks", {"_id": task.id}, _task_document(task))


async def _todo_ids(run: _Run) -> set[str]:
    return {str(raw["_id"]) async for raw in run.db["todos"].find(run.scope.filter(), {"_id": 1})}


async def _linking_todos(run: _Run) -> dict[str, str]:
    """Each generated workflow's todo, as the todo's own workflow_id names it."""
    filt = {**run.scope.filter(), "workflow_id": {"$type": "string"}}
    return {
        raw["workflow_id"]: str(raw["_id"])
        async for raw in run.db["todos"].find(filt, {"workflow_id": 1})
    }


def _todo_workflow_parent(
    workflow: LegacyWorkflow, todos: set[str], linking: dict[str, str]
) -> str | None:
    if not workflow.is_todo_workflow:
        return None
    if workflow.source_todo_id in todos:
        return workflow.source_todo_id
    return linking.get(workflow.id)


async def _migrate_workflows(run: _Run) -> None:
    todos, linking = await _todo_ids(run), await _linking_todos(run)
    async for raw in run.source(Phase.TASKS_FROM_WORKFLOWS, "workflows"):
        workflow = _mapped(run, "workflows", raw, LegacyWorkflow.model_validate, raw)
        if workflow is None or workflow.is_explore:
            continue
        parent = _todo_workflow_parent(workflow, todos, linking)
        if workflow.is_todo_workflow and parent is None:
            run.report.notes["todo_workflows_without_their_todo"] += 1
        task = _mapped(run, "workflows", raw, task_from_workflow, workflow, parent_id=parent)
        if task is not None:
            await run.replace(
                Phase.TASKS_FROM_WORKFLOWS, "tasks", {"_id": task.id}, _task_document(task)
            )


async def _migrate_templates(run: _Run) -> None:
    async for raw in run.source(Phase.TEMPLATES, "workflows"):
        if not raw.get("is_public") and not raw.get("is_explore"):
            continue
        workflow = _mapped(run, "workflows", raw, LegacyWorkflow.model_validate, raw)
        if workflow is None:
            continue
        template = _mapped(run, "workflows", raw, template_from_workflow, workflow)
        if template is not None:
            await run.replace(
                Phase.TEMPLATES,
                "task_templates",
                {"_id": template.id},
                _keyed(template, identity=template.id),
            )


async def _known_task_ids(run: _Run) -> set[str]:
    if not run.task_ids:
        run.task_ids = {
            raw["_id"] async for raw in run.db["tasks"].find(run.scope.filter(), {"_id": 1})
        }
    return run.task_ids


async def _expected_task_ids(run: _Run) -> set[str]:
    """Tasks this run writes or wrote: read back after an apply, derived from sources in a dry run."""
    if run.apply:
        return await _known_task_ids(run)
    ids = await _todo_ids(run)
    filt = {**run.scope.filter(), "is_explore": {"$ne": True}}
    ids |= {raw["_id"] async for raw in run.db["workflows"].find(filt, {"_id": 1})}
    return ids


async def _migrate_executions(run: _Run) -> None:
    tasks = await _expected_task_ids(run)
    async for raw in run.source(Phase.RUNS_FROM_EXECUTIONS, "workflow_executions"):
        execution = _mapped(run, "workflow_executions", raw, LegacyExecution.model_validate, raw)
        if execution is None:
            continue
        if execution.workflow_id not in tasks:
            run.report.notes["executions_of_deleted_workflows"] += 1
            continue
        record = _mapped(run, "workflow_executions", raw, run_from_execution, execution)
        if record is not None:
            await run.replace(
                Phase.RUNS_FROM_EXECUTIONS,
                "task_runs",
                {"run_id": record.run_id},
                _keyed(record, identity=None),
            )


async def _migrate_activity(run: _Run) -> None:
    async for raw in run.source(Phase.RUNS_FROM_ACTIVITY, "todos"):
        if not raw.get("activity_content"):
            continue
        todo = _mapped(run, "todos", raw, LegacyTodo.model_validate, raw)
        if todo is None:
            continue
        records = _mapped(run, "todos", raw, runs_from_activity, todo)
        for record in records or []:
            await run.replace(
                Phase.RUNS_FROM_ACTIVITY,
                "task_runs",
                {"run_id": record.run_id},
                _keyed(record, identity=None),
            )


async def _migrate_playbooks(run: _Run) -> None:
    async for raw in run.source(Phase.PLAYBOOKS, "playbooks"):
        playbook = _mapped(run, "playbooks", raw, LegacyPlaybook.model_validate, raw)
        if playbook is None:
            continue
        source = await run.db["workflows"].find_one(
            {"_id": playbook.workflow_id, "user_id": playbook.user_id}
        )
        if source is None or source.get("is_explore"):
            run.report.notes["playbooks_of_deleted_workflows"] += 1
            continue
        workflow = _mapped(run, "workflows", source, LegacyWorkflow.model_validate, source)
        if workflow is None:
            continue
        task_playbook = playbook_for_task(playbook, workflow)
        if task_playbook.body_hash == playbook.workflow_hash:
            run.report.notes["playbooks_already_stale"] += 1
        await run.replace(
            Phase.PLAYBOOKS,
            "task_playbooks",
            {"playbook_id": task_playbook.playbook_id},
            _keyed(task_playbook, identity=None),
        )


async def _add_field(
    run: _Run, phase: Phase, collection: str, key: Document, field_name: str, value: str
) -> None:
    """Give a shared document one new field; a document that already holds a value for it is left alone.

    A null counts as unset: today's models write their optional fields as null.
    """
    run.report.written[phase] += 1
    if run.apply:
        await run.db[collection].update_one(
            {**key, field_name: None}, {"$set": {field_name: value}}
        )


_CHAT_BINDING: Final[Document] = {
    "todo_id": 1,
    "metadata.workflow_id": 1,
    "system_purpose": 1,
    "createdAt": 1,
}


def _chat_created(raw: Document) -> str:
    return str(raw.get("createdAt") or "")


async def _migrate_conversations(run: _Run) -> None:
    """Bind each GAIA task's chat by task_id: a todo's own, and a workflow's oldest run chat."""
    tasks = await _expected_task_ids(run)
    workflow_chats: dict[str, Document] = {}
    async for raw in run.source(
        Phase.CONVERSATIONS, "conversations", projection=_CHAT_BINDING, resumable=False
    ):
        todo_id = raw.get("todo_id")
        if isinstance(todo_id, str) and todo_id in tasks:
            await _add_field(
                run, Phase.CONVERSATIONS, "conversations", {"_id": raw["_id"]}, "task_id", todo_id
            )
            continue
        workflow_id = (raw.get("metadata") or {}).get("workflow_id")
        if raw.get("system_purpose") != WORKFLOW_CHAT_PURPOSE or workflow_id not in tasks:
            continue
        held = workflow_chats.get(workflow_id)
        if held is None or _chat_created(raw) < _chat_created(held):
            workflow_chats[workflow_id] = raw
    for workflow_id, raw in workflow_chats.items():
        await _add_field(
            run, Phase.CONVERSATIONS, "conversations", {"_id": raw["_id"]}, "task_id", workflow_id
        )


async def _migrate_approvals(run: _Run) -> None:
    tasks = await _expected_task_ids(run)
    async for raw in run.source(Phase.APPROVALS, "approval_ledger"):
        owner = raw.get("owner_id")
        if raw.get("owner_run_type") in LEGACY_WAITERS and owner in tasks:
            await _add_field(
                run, Phase.APPROVALS, "approval_ledger", {"_id": raw["_id"]}, "owner_task_id", owner
            )


def _twin_key(raw: Document) -> Document | None:
    """The key a wait is kept under once it waits as a task; None when it already does."""
    waiter = raw["waiter"]
    condition = raw["condition"]
    if waiter not in LEGACY_WAITERS and condition != LEGACY_TRIGGER_CONDITION:
        return None
    return {
        "user_id": raw["user_id"],
        "condition": TASK_TRIGGER_CONDITION if condition == LEGACY_TRIGGER_CONDITION else condition,
        "subject_id": raw["subject_id"],
        "waiter": TASK_WAITER if waiter in LEGACY_WAITERS else waiter,
        "waiter_id": raw["waiter_id"],
    }


async def _migrate_waits(run: _Run) -> None:
    tasks = await _expected_task_ids(run)
    async for raw in run.source(Phase.WAITS, "waits"):
        key = _twin_key(raw)
        if key is None:
            continue
        if key["waiter"] == TASK_WAITER and key["waiter_id"] not in tasks:
            run.report.notes["waits_of_deleted_tasks"] += 1
            continue
        run.report.written[Phase.WAITS] += 1
        if run.apply:
            await run.db["waits"].update_one(
                key,
                {
                    "$setOnInsert": {
                        "subject_name": raw["subject_name"],
                        "stream_id": raw.get("stream_id"),
                        "created_at": raw["created_at"],
                    }
                },
                upsert=True,
            )


_PHASES: Final[tuple[Callable[[_Run], Awaitable[None]], ...]] = (
    _migrate_todos,
    _migrate_workflows,
    _migrate_templates,
    _migrate_executions,
    _migrate_activity,
    _migrate_playbooks,
    _migrate_conversations,
    _migrate_approvals,
    _migrate_waits,
)


async def migrate(
    db: AsyncIOMotorDatabase[Document],
    *,
    apply: bool,
    restart: bool = False,
    user_ids: Collection[str] | None = None,
) -> MigrationReport:
    """Run every phase in order against db; apply=False writes nothing and reports what it would."""
    run = _Run(
        db=db,
        scope=Scope(None if user_ids is None else frozenset(user_ids)),
        apply=apply,
        restart=restart,
        report=MigrationReport(applied=apply),
    )
    if restart and apply:
        await db[PROGRESS].delete_many({})
    for phase in _PHASES:
        await phase(run)
    return run.report
