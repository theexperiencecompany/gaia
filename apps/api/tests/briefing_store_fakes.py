"""In-memory stand-ins for the stores a brief run reads and writes, installed over the repository singletons.

Each fake holds its rows in memory and answers the run's queries with the repository's own filters
and order, so the run's real code runs over them in the hermetic unit tier. install() answers every
public coroutine of a singleton from its fake and fails one the fake does not answer, so nothing
reaches Mongo. Real store semantics are proven over real Mongo in tests/contracts and
tests/integration/real.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
import inspect
from operator import attrgetter
from typing import Any
from unittest.mock import _Call, call

from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.briefing import BriefForm, BriefingBag, BriefingKind
from app.constants.integrations import IntegrationStatus
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.brief_document_models import BriefCardRecord, BriefingModel, DeliveryStep
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_state_models import (
    BriefingBootstrap,
    BriefingStateDocument,
    BriefingWindDown,
    ShuffleBag,
)
from app.models.conversation_models import BotReplyRow
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.hil_models import (
    ApprovalLedgerDocument,
    HILApprovalRecord,
    HILApprovalStatus,
    LedgerState,
)
from app.models.integration_models import UserIntegrationDocument
from app.models.reminder_models import ReminderDocument
from app.models.scout_models import Sighted, SignalMemoryDocument
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.user_activity_models import UserActivityDates
from app.models.user_models import UserDocument
from app.models.workflow_execution_models import RunMoment, WorkflowExecutionDocument
from app.models.workflow_models import WorkflowDocument
from app.utils.timezone import as_utc


class Store:
    """A fake store's call log: what the run asked of it, in order, as mock calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, _Call]] = []

    def calls_to(self, name: str) -> list[_Call]:
        return [made for method, made in self.calls if method == name]


def _unanswered(repository: str, name: str) -> Callable[..., Awaitable[Any]]:
    async def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(f"{repository}.{name} has no in-memory answer; add it to its fake")

    return refuse


def _recorded(store: Store, name: str, method: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
    async def answer(*args: object, **kwargs: object) -> object:
        store.calls.append((name, call(*args, **kwargs)))
        return await method(*args, **kwargs)

    return answer


def install(monkeypatch: pytest.MonkeyPatch, repository: object, store: Store) -> None:
    """Answer every public coroutine of the repository singleton from store, recording each call."""
    for name, _ in inspect.getmembers(type(repository), inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        own = getattr(type(store), name, None)
        answer = (
            _recorded(store, name, getattr(store, name))
            if own is not None
            else _unanswered(type(repository).__name__, name)
        )
        monkeypatch.setattr(repository, name, answer)


def _at_or_after(moment: datetime | None, since: datetime) -> bool:
    stamped = as_utc(moment)
    return stamped is not None and stamped >= since


def _newest_first(docs: list[Any], key: Callable[[Any], datetime | None]) -> list[Any]:
    floor = datetime.min.replace(tzinfo=UTC)
    return sorted(docs, key=lambda d: as_utc(key(d)) or floor, reverse=True)


def _limited(docs: list[Any], limit: int) -> list[Any]:
    """Apply a Mongo limit, where 0 is none."""
    return docs[:limit] if limit else docs


class InMemoryUsers(Store):
    def __init__(self, *users: UserDocument) -> None:
        super().__init__()
        self.rows: dict[str, UserDocument] = {u.id: u for u in users if u.id}

    async def get(self, user_id: str) -> UserDocument | None:
        user = self.rows.get(user_id)
        return user.model_copy(deep=True) if user else None

    async def get_activity_dates(self, user_id: str) -> UserActivityDates | None:
        user = self.rows.get(user_id)
        if user is None:
            return None
        return UserActivityDates(last_active_at=user.last_active_at, created_at=user.created_at)


class InMemoryBriefings(Store):
    """The briefings collection: unique per (user, date, kind), keyed by brief id."""

    def __init__(self, fresh_id: str) -> None:
        super().__init__()
        #: The id a brief not stored yet is given.
        self.fresh_id = fresh_id
        self.rows: dict[str, BriefingModel] = {}

    def _of(self, user_id: str) -> list[BriefingModel]:
        return [b for b in self.rows.values() if b.user_id == user_id]

    def _find(self, user_id: str, date: str, kind: BriefingKind) -> BriefingModel | None:
        return next((b for b in self._of(user_id) if (b.date, b.kind) == (date, kind)), None)

    async def get(self, briefing_id: str, *, user_id: str) -> BriefingModel | None:
        brief = self.rows.get(briefing_id)
        return brief.model_copy(deep=True) if brief and brief.user_id == user_id else None

    async def get_before_date(
        self, user_id: str, *, kind: BriefingKind, before_date: str
    ) -> BriefingModel | None:
        earlier = [b for b in self._of(user_id) if b.kind == kind and b.date < before_date]
        return max(earlier, key=lambda b: b.date).model_copy(deep=True) if earlier else None

    async def list_recent(
        self,
        user_id: str,
        *,
        limit: int,
        kind: BriefingKind | None = None,
        editions_only: bool = False,
    ) -> list[BriefingModel]:
        found = [
            b
            for b in self._of(user_id)
            if (kind is None or b.kind == kind)
            and not (editions_only and b.payload.form is BriefForm.QUIET_NOTE)
            and b.delivery is not None
            and b.delivery.completed_at is not None
        ]
        found.sort(key=lambda b: (b.date, b.kind), reverse=True)
        return [b.model_copy(deep=True) for b in _limited(found, limit)]

    async def list_stamped(self, user_id: str) -> list[BriefCardRecord]:
        delivered = sorted(
            (
                b
                for b in self._of(user_id)
                if b.payload.stamp_city is not None
                and b.delivery is not None
                and b.delivery.completed_at is not None
            ),
            key=lambda b: b.date,
        )
        first: dict[str, BriefingModel] = {}
        for brief in delivered:
            first.setdefault(brief.payload.stamp_city or "", brief)
        return [
            BriefCardRecord.model_validate(
                {
                    "id": b.id,
                    "date": b.date,
                    "kind": b.kind,
                    "edition": b.edition,
                    "payload": b.payload.model_dump(),
                }
            )
            for b in sorted(first.values(), key=lambda b: b.date)
        ]

    async def has_daily_briefing(self, user_id: str) -> bool:
        return any(b.kind == BriefingKind.DAILY for b in self._of(user_id))

    async def was_delivered(self, user_id: str, date: str, kind: BriefingKind) -> bool:
        brief = self._find(user_id, date, kind)
        return (
            brief is not None
            and brief.delivery is not None
            and brief.delivery.completed_at is not None
        )

    async def find_for_date(
        self, user_id: str, date: str, kind: BriefingKind
    ) -> BriefingModel | None:
        brief = self._find(user_id, date, kind)
        return brief.model_copy(deep=True) if brief else None

    async def briefing_id_for(self, user_id: str, date: str, kind: BriefingKind) -> str:
        existing = self._find(user_id, date, kind)
        return existing.id if existing else self.fresh_id

    async def upsert_briefing(self, brief: BriefingModel) -> BriefingModel:
        """Set the payload, link, edition and delivery; a new row starts undelivered and unopened."""
        twin = self._find(brief.user_id, brief.date, brief.kind)
        if twin is not None and twin.id != brief.id:
            raise DuplicateKeyError("E11000 duplicate key error (user_id, date, kind)")
        before = self.rows.get(brief.id)
        stored = brief.model_copy(
            update={
                "payload": brief.payload.model_copy(deep=True),
                "delivery": brief.delivery.model_copy(deep=True) if brief.delivery else None,
                "created_at": before.created_at if before else datetime.now(UTC),
                "delivered_channels": list(before.delivered_channels) if before else [],
                "opened_at": before.opened_at if before else None,
            }
        )
        self.rows[brief.id] = stored
        return stored.model_copy(deep=True)

    async def record_step(
        self, user_id: str, briefing_id: str, step: DeliveryStep, reached: list[str]
    ) -> None:
        brief = self.rows.get(briefing_id)
        if brief is None or brief.user_id != user_id or brief.delivery is None:
            return
        if step not in brief.delivery.done:
            brief.delivery.done.append(step)
        brief.delivered_channels.extend(c for c in reached if c not in brief.delivered_channels)

    async def complete_delivery(self, user_id: str, briefing_id: str) -> None:
        brief = self.rows.get(briefing_id)
        if brief is not None and brief.user_id == user_id and brief.delivery is not None:
            brief.delivery.completed_at = datetime.now(UTC)


class InMemoryBriefingState(Store):
    """The briefing_state collection: one row per user; a user with none reads every default."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, BriefingStateDocument] = {}

    def row(self, user_id: str) -> BriefingStateDocument:
        return self.rows.setdefault(user_id, BriefingStateDocument(user_id=user_id))

    def _wind_down(self, user_id: str) -> BriefingWindDown:
        state = self.row(user_id)
        if state.wind_down is None:
            state.wind_down = BriefingWindDown()
        return state.wind_down

    async def state_for(self, user_id: str) -> BriefingStateDocument:
        state = self.rows.get(user_id)
        return state.model_copy(deep=True) if state else BriefingStateDocument(user_id=user_id)

    async def set_bag(self, user_id: str, bag: BriefingBag, state: ShuffleBag) -> None:
        self.row(user_id).shuffle_bags[BriefingBag(bag)] = state.model_copy(deep=True)

    async def hold_for_goal(self, user_id: str) -> None:
        state = self.row(user_id)
        if state.bootstrap is None:
            state.bootstrap = BriefingBootstrap(pending=True, since=datetime.now(UTC))

    async def clear_bootstrap(self, user_id: str) -> None:
        self.row(user_id).bootstrap = None

    async def set_idle_day(self, user_id: str, *, idle_days: int, date_str: str) -> None:
        marker = self._wind_down(user_id)
        marker.idle_days, marker.date = idle_days, date_str

    async def enter_wind_down(self, user_id: str) -> None:
        self._wind_down(user_id).wound_down_since = datetime.now(UTC)

    async def record_goal_question(self, user_id: str) -> None:
        self._wind_down(user_id).goal_asked_at = datetime.now(UTC)

    async def clear_wind_down(self, user_id: str) -> None:
        marker = self._wind_down(user_id)
        marker.wound_down_since, marker.idle_days, marker.date = None, 0, None


class InMemoryPendingBriefItems(Store):
    """Results held for the next brief, read oldest first and cleared once a brief carried them."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[PendingBriefItemDocument] = []
        #: Each clearing's ids, in order: what every delivered brief consumed.
        self.consumed: list[list[str]] = []

    async def list_for_user(
        self,
        user_id: str,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[PendingBriefItemDocument]:
        mine = [r for r in self.rows if r.user_id == user_id]
        for field, direction in reversed(sort or []):
            mine.sort(key=attrgetter(field), reverse=direction < 0)
        return [r.model_copy(deep=True) for r in _limited(mine[skip:], limit)]

    async def consume(self, user_id: str, item_ids: list[str]) -> int:
        self.consumed.append(list(item_ids))
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r.user_id == user_id and r.id in item_ids)]
        return before - len(self.rows)


class InMemorySignalMemory(Store):
    """What the brief remembers of each signal, keyed by (user, integration, external id)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[SignalMemoryDocument] = []

    def _matching(self, user_id: str, signals: Sequence[Sighted]) -> list[SignalMemoryDocument]:
        keys = {(s.integration_id, s.external_id) for s in signals}
        return [
            r
            for r in self.rows
            if r.user_id == user_id and (r.integration_id, r.external_id) in keys
        ]

    async def find_for(
        self, user_id: str, signals: Sequence[Sighted]
    ) -> list[SignalMemoryDocument]:
        return [r.model_copy(deep=True) for r in self._matching(user_id, signals)]

    async def record_seen(self, user_id: str, signals: Sequence[Sighted], at: datetime) -> None:
        for signal in signals:
            [row] = self._matching(user_id, [signal]) or [None]
            if row is None:
                row = SignalMemoryDocument(
                    user_id=user_id,
                    integration_id=signal.integration_id,
                    external_id=signal.external_id,
                    first_seen=at,
                )
                self.rows.append(row)
            row.last_state, row.last_seen = signal.state, at

    async def mark_shown(self, user_id: str, signals: Sequence[Sighted], at: datetime) -> None:
        for row in self._matching(user_id, signals):
            row.times_shown += 1
            row.last_shown = at


def _own(doc: TodoDocument) -> bool:
    return GAIA_TRACKED_LABEL not in doc.labels


def _about(doc: TodoDocument, ref: ExternalRef) -> bool:
    held = doc.external_ref
    return held is not None and (held.source, held.id) == (ref.source, ref.id)


class InMemoryTodos(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, TodoDocument] = {}

    def add(self, *docs: TodoDocument) -> None:
        for doc in docs:
            self.rows[doc.id or f"todo-{len(self.rows)}"] = doc

    def _of(self, user_id: str) -> list[TodoDocument]:
        return [d for d in self.rows.values() if d.user_id == user_id]

    async def list_active_tracked(self, user_id: str, *, limit: int) -> list[TodoDocument]:
        open_tracked = [d for d in self._of(user_id) if not _own(d) and not d.completed]
        return _limited(_newest_first(open_tracked, lambda d: d.updated_at), limit)

    async def list_completed_since(self, user_id: str, *, since: datetime) -> list[TodoDocument]:
        done = [d for d in self._of(user_id) if d.completed and _at_or_after(d.completed_at, since)]
        return _newest_first(done, lambda d: d.completed_at)

    async def list_external_ref_activity_since(
        self, user_id: str, source: ExternalRefSource, *, since: datetime
    ) -> list[TodoDocument]:
        return [
            d
            for d in self._of(user_id)
            if d.external_ref is not None
            and d.external_ref.source is source
            and (_at_or_after(d.created_at, since) or _at_or_after(d.completed_at, since))
        ]

    async def list_open_user_todos(self, user_id: str, *, limit: int) -> list[TodoDocument]:
        own_open = [d for d in self._of(user_id) if _own(d) and not d.completed]
        return _limited(_newest_first(own_open, lambda d: d.updated_at), limit)

    async def find_latest_by_external_ref(
        self, user_id: str, ref: ExternalRef
    ) -> TodoDocument | None:
        about = _newest_first(
            [d for d in self._of(user_id) if _about(d, ref)], lambda d: d.created_at
        )
        return about[0] if about else None


class InMemoryWorkflows(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[WorkflowDocument] = []

    async def find_by_ids_for_user(
        self, workflow_ids: list[str], user_id: str
    ) -> list[WorkflowDocument]:
        return [w for w in self.rows if w.id in workflow_ids and w.user_id == user_id]

    async def find_system_workflows(
        self, user_id: str, system_workflow_keys: Sequence[str]
    ) -> list[WorkflowDocument]:
        return [
            w
            for w in self.rows
            if w.user_id == user_id
            and w.is_system_workflow
            and w.system_workflow_key in system_workflow_keys
        ]


class InMemoryWorkflowExecutions(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[WorkflowExecutionDocument] = []

    def _since(
        self, user_id: str, since: datetime, exclude_workflow_ids: Sequence[str]
    ) -> list[WorkflowExecutionDocument]:
        return [
            e
            for e in self.rows
            if e.user_id == user_id
            and _at_or_after(e.started_at, since)
            and e.workflow_id not in exclude_workflow_ids
        ]

    async def list_since(
        self,
        user_id: str,
        since: datetime,
        *,
        exclude_workflow_ids: Sequence[str],
        limit: int,
        status: str | None = None,
    ) -> list[WorkflowExecutionDocument]:
        found = [
            e
            for e in self._since(user_id, since, exclude_workflow_ids)
            if status is None or e.status == status
        ]
        return _limited(_newest_first(found, lambda e: e.started_at), limit)

    async def list_run_moments_since(
        self, user_id: str, since: datetime, *, exclude_workflow_ids: Sequence[str]
    ) -> list[RunMoment]:
        return [
            RunMoment(started_at=e.started_at, status=e.status)
            for e in self._since(user_id, since, exclude_workflow_ids)
        ]


class InMemoryEmailVerdicts(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[EmailVerdictDocument] = []

    async def list_since(self, user_id: str, *, since: datetime) -> list[EmailVerdictDocument]:
        return [v for v in self.rows if v.user_id == user_id and _at_or_after(v.created_at, since)]


class InMemoryApprovalLedger(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[ApprovalLedgerDocument] = []

    async def list_pending_for_user(self, user_id: str) -> list[ApprovalLedgerDocument]:
        pending = [r for r in self.rows if r.user_id == user_id and r.state == LedgerState.PENDING]
        return sorted(
            pending, key=lambda r: as_utc(r.created_at) or datetime.min.replace(tzinfo=UTC)
        )


class InMemoryHILApprovals(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[HILApprovalRecord] = []

    async def list_pending_for_user(self, user_id: str, now: datetime) -> list[HILApprovalRecord]:
        return [
            r
            for r in self.rows
            if r.user_id == user_id
            and r.status is HILApprovalStatus.PENDING
            and (as_utc(r.expires_at) or now) > now
        ]


class InMemoryReminders(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[ReminderDocument] = []

    async def find_scheduled_between(
        self, user_id: str, start: datetime, end: datetime
    ) -> list[ReminderDocument]:
        due = [
            r
            for r in self.rows
            if r.user_id == user_id
            and (at := as_utc(r.scheduled_at)) is not None
            and start <= at < end
        ]
        return sorted(due, key=lambda r: as_utc(r.scheduled_at) or start)


class InMemoryConversations(Store):
    def __init__(self) -> None:
        super().__init__()
        #: The user's bot-platform messages, newest first, each with when it was sent.
        self.bot_replies: list[tuple[str, datetime, BotReplyRow]] = []

    async def list_bot_replies_since(
        self, user_id: str, since: datetime, *, limit: int
    ) -> list[BotReplyRow]:
        newer = [row for owner, at, row in self.bot_replies if owner == user_id and at > since]
        return _limited(newer, limit)


class InMemoryUserIntegrations(Store):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[UserIntegrationDocument] = []

    def connect(self, user_id: str, *integration_ids: str) -> None:
        self.rows = [r for r in self.rows if r.user_id != user_id]
        self.rows += [
            UserIntegrationDocument(
                user_id=user_id, integration_id=i, status=IntegrationStatus.CONNECTED
            )
            for i in integration_ids
        ]

    async def list_for_user(
        self,
        user_id: str,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[UserIntegrationDocument]:
        return _limited([r for r in self.rows if r.user_id == user_id][skip:], limit)
