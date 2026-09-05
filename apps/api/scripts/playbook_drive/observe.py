"""What one fire did, read where it is authoritative.

The execution record and the playbook come from Mongo; the playbook
lifecycle's own account of the fire (mode, reason, for_each counts, a discard)
comes from the worker's wide events, which the worker writes as JSON lines. A
scenario asserts on this ``Observation`` and nothing else: never on prose.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any, cast

from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.database import Database
import redis

from app.config.settings import settings
from app.constants.cache import RATE_LIMIT_KEY_PREFIX
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME

from .client import EXECUTION_WAIT_SECONDS, SETTLE_SECONDS, Execution, GaiaClient

FINISHED = frozenset({"success", "failed"})


class PlaybookState(BaseModel):
    playbook_id: str
    revision: int
    last_run_status: str
    suspect_streak: int
    heal_attempts: int
    tools: list[str]
    has_for_each: bool
    has_handoff: bool


class WorkflowState(BaseModel):
    activated: bool
    deactivated_reason: str | None
    playbook_declines: int
    blocked_on_integrations: list[str]
    last_discard_reason: str | None


class ForEachCount(BaseModel):
    step: str
    items: int
    ran: int


class Observation(BaseModel):
    """One fire, after it settled."""

    execution: Execution
    playbook: PlaybookState | None
    workflow: WorkflowState
    modes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    discards: list[str] = Field(default_factory=list)
    for_each: list[ForEachCount] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def warned(self, needle: str) -> bool:
        return any(needle in line for line in self.warnings + self.errors)


class WorkerLog:
    """The worker's JSON log, read from where the fire started."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def position(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0

    def events_since(self, position: int, workflow_id: str) -> Iterator[dict[str, Any]]:
        with self.path.open() as handle:
            handle.seek(position)
            for line in handle:
                if not line.startswith("{"):
                    continue
                try:
                    event: dict[str, Any] = json.loads(line)
                except ValueError:
                    continue
                if event.get("workflow_id") == workflow_id:
                    yield event


class Store:
    """Direct reads of the collections a fire writes. Reads only; the drive
    changes state through the API."""

    def __init__(self) -> None:
        client: MongoClient[dict[str, Any]] = MongoClient(settings.MONGO_DB)
        self.db: Database[dict[str, Any]] = client[MONGO_DATABASE_NAME]
        self.redis = redis.Redis.from_url(settings.REDIS_URL)

    def reset_rate_limits(self, user_id: str) -> int:
        """Clear the dev user's tiered rate-limit counters.

        Sixty fires in a quarter of an hour is a drive, not a user, and the
        limiter is right to refuse it; the drive is about the playbook surface,
        so the counters are cleared before each fire rather than the limit
        raised for everyone. Dev tool, dev user: never point this at production.
        """
        keys = list(self.redis.scan_iter(match=f"{RATE_LIMIT_KEY_PREFIX}:{user_id}:*"))
        return cast(int, self.redis.delete(*keys)) if keys else 0

    def playbook(self, workflow_id: str) -> PlaybookState | None:
        raw = self.db["playbooks"].find_one({"workflow_id": workflow_id})
        if raw is None:
            return None
        steps: list[dict[str, Any]] = raw.get("steps") or []
        return PlaybookState(
            playbook_id=raw["playbook_id"],
            revision=raw.get("revision", 0),
            last_run_status=raw.get("last_run_status", "not_run"),
            suspect_streak=raw.get("suspect_streak", 0),
            heal_attempts=raw.get("heal_attempts", 0),
            tools=_tools(steps),
            has_for_each=any(_has_key(steps, "for_each")),
            has_handoff=any(_has_key(steps, "handoff")),
        )

    def workflow(self, workflow_id: str) -> WorkflowState:
        raw = self.db["workflows"].find_one({"_id": workflow_id})
        if raw is None:
            raise RuntimeError(f"workflow {workflow_id} vanished")
        discard = raw.get("last_playbook_discard") or {}
        return WorkflowState(
            activated=bool(raw.get("activated")),
            deactivated_reason=raw.get("deactivated_reason"),
            playbook_declines=raw.get("playbook_declines") or 0,
            blocked_on_integrations=list(raw.get("blocked_on_integrations") or []),
            last_discard_reason=discard.get("reason"),
        )

    def executions(self, workflow_id: str) -> list[Execution]:
        rows = self.db["workflow_executions"].find({"workflow_id": workflow_id})
        return [
            Execution(
                execution_id=row["execution_id"],
                status=row.get("status", "running"),
                started_at=row["started_at"],
                error_message=row.get("error_message"),
                summary=row.get("summary"),
            )
            for row in rows.sort("started_at", -1)
        ]

    def count_todos(self, user_id: str, title_regex: str) -> int:
        return self.db["todos"].count_documents(
            {"user_id": user_id, "title": {"$regex": title_regex}}
        )

    def count_notifications(self, user_id: str, since: datetime, title_regex: str) -> int:
        return self.db["notifications"].count_documents(
            {
                "user_id": user_id,
                "created_at": {"$gte": since},
                "original_request.content.title": {"$regex": title_regex},
            }
        )

    def edit_workflow_prompt(self, workflow_id: str, prompt: str) -> None:
        """The one write: an edit behind the API's back, so the stale-hash discard
        is exercised without regenerating the steps."""
        self.db["workflows"].update_one({"_id": workflow_id}, {"$set": {"prompt": prompt}})


def fire_and_observe(
    client: GaiaClient, store: Store, log: WorkerLog, workflow_id: str, *, user_id: str
) -> Observation:
    """Execute once, wait for the record to finish, let bookkeeping land, read everything."""
    before = len(store.executions(workflow_id))
    position = log.position()
    store.reset_rate_limits(user_id)
    client.execute(workflow_id)
    deadline = time.monotonic() + EXECUTION_WAIT_SECONDS
    while time.monotonic() < deadline:
        executions = store.executions(workflow_id)
        if len(executions) > before and executions[0].status in FINISHED:
            time.sleep(SETTLE_SECONDS)
            return _observe(store, log, workflow_id, position, executions[0])
        time.sleep(5)
    raise TimeoutError(f"fire of {workflow_id} did not finish within {EXECUTION_WAIT_SECONDS}s")


def _observe(
    store: Store, log: WorkerLog, workflow_id: str, position: int, execution: Execution
) -> Observation:
    observation = Observation(
        execution=execution,
        playbook=store.playbook(workflow_id),
        workflow=store.workflow(workflow_id),
    )
    for event in log.events_since(position, workflow_id):
        playbook = event.get("playbook")
        if isinstance(playbook, dict):
            if mode := playbook.get("mode"):
                observation.modes.append(str(mode))
            if reason := playbook.get("reason"):
                observation.reasons.append(str(reason))
            if isinstance(playbook.get("for_each"), dict):
                observation.for_each.append(ForEachCount.model_validate(playbook["for_each"]))
        if str(event.get("message", "")).endswith("Playbook discarded"):
            observation.discards.append(str(event.get("reason")))
        for warning in event.get("warnings") or []:
            observation.warnings.append(_message(warning))
        for error in event.get("errors") or []:
            observation.errors.append(_message(error))
    return observation


def _message(entry: object) -> str:
    return str(entry.get("msg", "")) if isinstance(entry, dict) else str(entry)


def _tools(steps: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for step in steps:
        if step.get("handoff"):
            names.extend(_tools(step.get("steps") or []))
        elif step.get("tool"):
            names.append(str(step["tool"]))
    return names


def _has_key(steps: list[dict[str, Any]], key: str) -> Iterator[bool]:
    for step in steps:
        yield step.get(key) is not None
        yield from _has_key(step.get("steps") or [], key)
