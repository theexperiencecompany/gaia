"""State machine for GAIA-assigned todos.

Owns every ``execution_status`` transition and the gates around them:

- creation gate — traceability (``serves``) + server-side budgets (the junk-todo fix)
- ``approve`` — the ONLY ``proposed → queued`` path; meters the free tier and
  turns an at-quota tap into the upgrade pitch instead of a silent failure
- ``dismiss`` / ``expire`` — rejection paths that teach memory (3-strike rule)
- ``handoff`` — user todo → GAIA-assigned
- worker transitions — ``queued → running → done | failed | needs_you``

Canvas/context formatting lives in ``tracked_todo_service``, which depends on
this module — never the reverse.
"""

from datetime import UTC, datetime, timedelta
import re
from typing import Any, cast

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    tiered_limiter,
)
from app.constants.memory import MemorySourceType
from app.constants.notifications import (
    NOTIFICATION_KIND_TODO_NEEDS_YOU,
)
from app.constants.todos import (
    ASSIGNEE_GAIA,
    DELIVERABLE_TEMPLATE,
    FACET_LOG,
    FACET_NOTES,
    FAILED_LABEL,
    GAIA_TODO_EXECUTIONS_FEATURE,
    MAX_ACTIVE_GOALS,
    MAX_GAIA_TODOS_IN_FLIGHT,
    MAX_GAIA_USER_RETRIES,
    MAX_PENDING_PROPOSALS,
    NOTES_TEMPLATE,
    PITCH_TTL_DAYS,
    PROPOSAL_REJECTED_MEMORY_CATEGORY,
    PROPOSAL_TTL_HOURS,
    REJECTION_STRIKE_THRESHOLD,
)
from app.core.websocket_manager import WebSocketManager
from app.db.repositories.todos import todo_repository
from app.memory.engine import memory_engine
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.payment_models import PlanType
from app.models.todo_models import ExecutionStatus, TodoDocument, TodoUpdate
from app.services import first_steps_service
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.services.notification_service import notification_service
from app.services.todo_canvas_storage import append_facet, build_vfs_label
from app.utils.analytics import track
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log

# Statuses counted against MAX_GAIA_TODOS_IN_FLIGHT.
IN_FLIGHT_STATUSES: tuple[str, ...] = (
    ExecutionStatus.QUEUED.value,
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.NEEDS_YOU.value,
)
# Labels that are system bookkeeping, never a proposal "kind".
_RESERVED_KIND_LABELS: frozenset[str] = frozenset({FAILED_LABEL})


class GaiaTodoError(Exception):
    """Base for GAIA-todo lifecycle rejections (budget, traceability, transition)."""


class BudgetExceededError(GaiaTodoError):
    """Creation rejected because a GAIA-todo budget cap is already full."""


class TraceabilityError(GaiaTodoError):
    """Creation rejected because ``serves`` was empty (untraceable todo)."""


class InvalidTransitionError(GaiaTodoError):
    """A lifecycle transition was requested from a state that does not allow it."""


class ExecutionQuotaError(GaiaTodoError):
    """Approve blocked at the metered execution quota.

    Carries what the API layer needs to render the upgrade CTA: the pitch of
    the specific staged work, the quota reset time, and the required plan.
    """

    def __init__(
        self,
        *,
        todo_id: str,
        reset_time: str | None,
        pitch: str,
        plan_required: str = "pro",
    ) -> None:
        self.todo_id = todo_id
        self.reset_time = reset_time
        self.pitch = pitch
        self.plan_required = plan_required
        super().__init__(f"GAIA execution quota reached for todo {todo_id}")


def derive_proposal_kind(doc: TodoDocument) -> str:
    """Stable category for a proposal, used to group rejection signals.

    First non-reserved label, else a slug of the title — so the 3-strike rule
    still groups repeated proposals of the same shape.
    """
    for label in doc.labels:
        if label not in _RESERVED_KIND_LABELS:
            return label
    title = (doc.title or "untitled").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", title).strip("-")[:60] or "untitled"


def _build_upgrade_pitch(doc: TodoDocument) -> str:
    """One-line pitch naming the specific staged work behind an at-quota Approve."""
    what = doc.serves or doc.title or "this work"
    return f"GAIA has '{doc.title or 'this todo'}' staged and ready ({what}) — upgrade to run it."


def _is_gaia_assigned(doc: TodoDocument) -> bool:
    return doc.assignee == ASSIGNEE_GAIA


async def _get_gaia_todo(todo_id: str, user_id: str) -> TodoDocument:
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        raise InvalidTransitionError(f"Todo {todo_id} not found")
    if not _is_gaia_assigned(doc):
        raise InvalidTransitionError(f"Todo {todo_id} is not GAIA-assigned")
    return doc


async def _require_status(
    todo_id: str, user_id: str, expected: ExecutionStatus, action: str
) -> TodoDocument:
    doc = await _get_gaia_todo(todo_id, user_id)
    if doc.execution_status != expected:
        raise InvalidTransitionError(
            f"Only {expected.value} todos can be {action} "
            f"(todo {todo_id} is {doc.execution_status!r})"
        )
    return doc


async def system_log(todo_id: str, user_id: str, event_type: str, details: str) -> None:
    """Append an audit entry to the todo's log.md (code-written, not agent)."""
    now = datetime.now(UTC)
    await append_facet(
        todo_id, user_id, FACET_LOG, f"\n## {now.isoformat()} [{event_type}]\n- {details}\n"
    )


async def _broadcast_status(user_id: str, todo_id: str, status: str) -> None:
    """Push the transition to the user's open sessions (dashboard live updates).

    Best-effort by design: the state change is already persisted, so a push
    failure only delays the UI until its next refetch — log it, never raise.
    """
    try:
        await WebSocketManager().broadcast_to_user(
            user_id, {"type": "todo.execution_status", "todo_id": todo_id, "status": status}
        )
    except Exception as e:
        log.warning("gaia_todo.ws_broadcast_failed", todo_id=todo_id, error=str(e))


async def schedule_execution(todo_id: str, scheduled_at: datetime) -> bool:
    """Enqueue the ARQ deferred job that executes this todo at ``scheduled_at``."""
    try:
        pool = await RedisPoolManager.get_pool()
        await pool.enqueue_job("execute_tracked_todo", todo_id, _defer_until=scheduled_at)
        return True
    except Exception as e:
        log.warning("gaia_todo.schedule_failed", todo_id=todo_id, error=str(e))
        return False


async def reschedule_execution(todo_id: str, new_scheduled_at: datetime) -> bool:
    """Enqueue a replacement job; the task's Redis lock prevents double-execution."""
    return await schedule_execution(todo_id, new_scheduled_at)


async def gate_creation(
    user_id: str,
    serves: str,
    requires_approval: bool,
    title: str = "",
    kind: str = "task",
) -> tuple[str, ExecutionStatus | None]:
    """Validate a GAIA-todo creation and resolve its entry state.

    Returns the cleaned ``serves`` and the entry status per the approval rule
    (outward-facing → ``proposed``, internal-only → ``queued``). Raises
    ``TraceabilityError`` / ``BudgetExceededError`` — the junk-todo gate.
    Goal lanes (``kind == "goal"``) are long-lived by design: they skip the
    in-flight budget but are capped themselves so nightly attention stays
    focused.
    """
    serves = serves.strip()
    if kind == "goal":
        if not serves:
            raise TraceabilityError(
                "A goal needs `serves`: the user's own words for what they're pursuing."
            )
        active_goals = await todo_repository.count_open_goals(user_id)
        if active_goals >= MAX_ACTIVE_GOALS:
            raise BudgetExceededError(
                f"Already at {active_goals}/{MAX_ACTIVE_GOALS} active goals. A goal "
                "lane costs nightly attention: ask the user which goal to retire "
                "before adding this one."
            )
        # A goal is a lane, not executable work: it never enters the execution
        # pipeline (its children do).
        return serves, None
    if requires_approval and title.strip():
        # One Approve button per piece of work: an identically-titled pending
        # proposal means this is a duplicate (rerun, retry, or model repeat),
        # never a second legitimate ask.
        dupe = await todo_repository.find_pending_proposal_by_title(user_id, title.strip())
        if dupe:
            raise BudgetExceededError(
                f"A pending proposal titled {title.strip()!r} already exists "
                f"(id {dupe.id}). Update or approve that one instead of duplicating it."
            )
    if not serves:
        raise TraceabilityError(
            "GAIA todos must be traceable: pass `serves` naming the goal, "
            "memory item, or explicit user request this todo advances."
        )
    entry_status = ExecutionStatus.PROPOSED if requires_approval else ExecutionStatus.QUEUED
    if entry_status == ExecutionStatus.PROPOSED:
        cap, statuses, bucket = (
            MAX_PENDING_PROPOSALS,
            [ExecutionStatus.PROPOSED.value],
            "pending proposals",
        )
    else:
        cap, statuses, bucket = (
            MAX_GAIA_TODOS_IN_FLIGHT,
            list(IN_FLIGHT_STATUSES),
            "GAIA todos in flight",
        )
    existing = await todo_repository.list_budget_bucket(user_id, statuses=statuses, limit=cap + 1)
    if len(existing) >= cap:
        titles = "; ".join(doc.title or "untitled" for doc in existing[:cap])
        raise BudgetExceededError(
            f"Budget full: {len(existing)}/{cap} {bucket} ({titles}). "
            "Complete, dismiss, or let items expire before creating more."
        )
    return serves, entry_status


async def enforce_budget_post_insert(
    user_id: str, todo_id: str, entry_status: ExecutionStatus
) -> None:
    """Recount after insert and roll back the overshoot.

    The creation gate's check-then-insert is not atomic and the executor issues
    tool calls in parallel, so N creations can each pass the same count. The
    recount after insert makes the cap hold: the todo that tipped the bucket
    over deletes itself and surfaces the same budget error.
    """
    if entry_status is ExecutionStatus.PROPOSED:
        cap, statuses, bucket = (
            MAX_PENDING_PROPOSALS,
            [ExecutionStatus.PROPOSED.value],
            "pending proposals",
        )
    else:
        cap, statuses, bucket = (
            MAX_GAIA_TODOS_IN_FLIGHT,
            list(IN_FLIGHT_STATUSES),
            "GAIA todos in flight",
        )
    count = await todo_repository.count_budget_bucket(user_id, statuses=statuses)
    if count > cap:
        await todo_repository.delete(todo_id, user_id=user_id)
        raise BudgetExceededError(
            f"Budget full: {count - 1}/{cap} {bucket} already in place (parallel "
            "creations raced). Finish or dismiss existing items before adding more."
        )


async def _record_rejection_signal(
    user_id: str, doc: TodoDocument, source: str, reason: str | None = None
) -> None:
    """Persist a structured proposal_rejected memory signal (dismiss/expiry teach)."""
    content = (
        f"proposal_rejected | kind: {derive_proposal_kind(doc)} "
        f"| title: {doc.title or 'untitled'} | serves: {doc.serves or ''} "
        f"| source: {source}"
    )
    if reason:
        content += f" | reason: {reason}"
    try:
        await memory_engine.retain_single(
            user_id,
            content,
            category_path=PROPOSAL_REJECTED_MEMORY_CATEGORY,
            source_type=MemorySourceType.MANUAL,
        )
    except Exception as e:
        # The mongo-derived strike count still enforces the 3-strike rule;
        # losing the memory copy only weakens organic recall — log it.
        log.warning("gaia_todo.rejection_signal_failed", todo_id=doc.id, error=str(e))


async def approve(
    todo_id: str,
    user_id: str,
    user_plan: PlanType,
    channel: str = "web",
    instruction: str | None = None,
) -> None:
    """Approve a proposed todo: meter quota, queue it, enqueue execution.

    ``instruction`` carries the user's verbatim qualifying words at approval
    ("only send the Sequoia one") — persisted on the doc and injected into the
    release run, where it overrides the staged content on conflict.

    At quota, marks the proposal as the active upgrade pitch (TTL-exempt for
    PITCH_TTL_DAYS) and raises ``ExecutionQuotaError`` with the staged work.
    """
    doc = await _require_status(todo_id, user_id, ExecutionStatus.PROPOSED, "approved")
    now = datetime.now(UTC)
    try:
        await tiered_limiter.check_and_increment(user_id, GAIA_TODO_EXECUTIONS_FEATURE, user_plan)
    except RateLimitExceededException as e:
        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(pitch_expires_at=now + timedelta(days=PITCH_TTL_DAYS)),
        )
        track(
            user_id,
            "upgrade_prompt_shown",
            {"todo_id": todo_id, "feature": GAIA_TODO_EXECUTIONS_FEATURE, "channel": channel},
        )
        # RateLimitExceededException always assigns a dict to detail at runtime
        # (HTTPException types it str | None) — cast per Type Safety item 12.
        detail: dict = cast(dict, e.detail) if e.detail is not None else {}
        raise ExecutionQuotaError(
            todo_id=todo_id,
            reset_time=detail.get("reset_time"),
            pitch=_build_upgrade_pitch(doc),
            plan_required=detail.get("plan_required") or "pro",
        ) from e
    await todo_repository.update(
        todo_id,
        user_id=user_id,
        update=TodoUpdate(
            execution_status=ExecutionStatus.QUEUED,
            scheduled_at=now,
            pitch_expires_at=None,
            # Approval means "do it now" — the execution must PERFORM the
            # outward action from the deliverable, not re-draft it.
            execution_intent="release",
            # Always set (None clears a stale instruction from a prior cycle).
            approve_instruction=instruction,
        ),
    )
    await schedule_execution(todo_id, now)
    log_detail = f"User approved execution via {channel}"
    if instruction:
        log_detail += f' with instruction: "{instruction}"'
    await system_log(todo_id, user_id, "approved", log_detail)
    track(
        user_id,
        "todo_approved",
        {"todo_id": todo_id, "channel": channel, "has_instruction": bool(instruction)},
    )
    await first_steps_service.mark_step(user_id, first_steps_service.STEP_FIRST_APPROVE)
    await _broadcast_status(user_id, todo_id, ExecutionStatus.QUEUED.value)
    schedule_gaia_tasks_sync(user_id)


async def dismiss(
    todo_id: str, user_id: str, reason: str | None = None, channel: str = "web"
) -> None:
    """Dismiss a proposed todo; the rejection teaches memory (3-strike rule)."""
    doc = await _require_status(todo_id, user_id, ExecutionStatus.PROPOSED, "dismissed")
    # Persist the verbatim reason (and when) on the doc so the strike summary can
    # surface it without reaching into memory recall — the summary stays derived
    # from the todos collection, where the 3-strike rule cannot silently degrade.
    await todo_repository.update(
        todo_id,
        user_id=user_id,
        update=TodoUpdate(
            execution_status=ExecutionStatus.DISMISSED,
            completed=True,
            dismiss_reason=reason,
            dismissed_at=datetime.now(UTC),
        ),
    )
    await _record_rejection_signal(user_id, doc, "dismissed", reason)
    track(
        user_id,
        "todo_dismissed",
        {"todo_id": todo_id, "channel": channel, "has_reason": bool(reason)},
    )
    await _broadcast_status(user_id, todo_id, ExecutionStatus.DISMISSED.value)
    schedule_gaia_tasks_sync(user_id)


async def handoff(todo_id: str, user_id: str) -> None:
    """Convert a user todo to GAIA-assigned and enqueue it (entry state queued).

    Handoff never needs a tap: outward-facing steps discovered during execution
    flip the todo to ``needs_you`` per the run's approval contract.
    """
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        raise InvalidTransitionError(f"Todo {todo_id} not found")
    if _is_gaia_assigned(doc):
        raise InvalidTransitionError(f"Todo {todo_id} is already GAIA-assigned")
    now = datetime.now(UTC)
    title = doc.title or "untitled"
    update_kwargs: dict[str, Any] = {
        "assignee": ASSIGNEE_GAIA,
        "execution_status": ExecutionStatus.QUEUED,
        "serves": f"user handoff: {title}",
        "scheduled_at": now,
    }
    # Seed facets only if the todo has no working memory yet — a prep-classified
    # user todo may already carry notes_content (see todo_classification).
    if not doc.notes_content and not doc.canvas_content:
        update_kwargs["vfs_path"] = build_vfs_label(todo_id)
        update_kwargs["deliverable_content"] = DELIVERABLE_TEMPLATE.format(title=title)
        update_kwargs["notes_content"] = NOTES_TEMPLATE.format(title=title)
        update_kwargs["log_content"] = (
            f"# System Log: {title}\n\n## {now.isoformat()} [HANDOFF]\n- Source: user\n"
        )
    # assignee is the discriminator; no gaia-tracked label stamp (see create).
    await todo_repository.update(todo_id, user_id=user_id, update=TodoUpdate(**update_kwargs))
    await schedule_execution(todo_id, now)
    await system_log(todo_id, user_id, "handoff", "User handed this todo to GAIA")
    track(user_id, "handoff_created", {"todo_id": todo_id})
    await _broadcast_status(user_id, todo_id, ExecutionStatus.QUEUED.value)
    schedule_gaia_tasks_sync(user_id)


async def mark_execution_status(
    todo_id: str,
    user_id: str,
    status: ExecutionStatus,
    error_message: str | None = None,
    blocker_question: str | None = None,
) -> None:
    """Worker-owned transitions (``queued → running → done | failed | needs_you``).

    ``failed`` requires a human-readable cause and renders as loudly as ``done``.
    ``needs_you`` carries the blocking question so every surface can ask it and
    ``answer`` can resume the run.
    """
    if status == ExecutionStatus.FAILED and not (error_message or "").strip():
        raise InvalidTransitionError("failed status requires an error_message cause")
    await todo_repository.update(
        todo_id,
        user_id=user_id,
        update=TodoUpdate(
            execution_status=status,
            error_message=error_message if status == ExecutionStatus.FAILED else None,
            blocker_question=blocker_question if status == ExecutionStatus.NEEDS_YOU else None,
        ),
    )
    if status == ExecutionStatus.DONE:
        track(user_id, "gaia_todo_completed", {"todo_id": todo_id})
    if status == ExecutionStatus.NEEDS_YOU:
        # Fires for both entry points into needs_you — the agent's ``block`` and
        # the release honesty gate both route here, so a paused run always pings.
        await _notify_needs_you(todo_id, user_id, blocker_question)
    await _broadcast_status(user_id, todo_id, status.value)
    schedule_gaia_tasks_sync(user_id)


def _blocker_line(doc: TodoDocument) -> str:
    title = doc.title or "a todo"
    question = (doc.blocker_question or "").strip() or "needs a decision from you to continue."
    return f"- {title}: {question}"


async def _notify_needs_you(todo_id: str, user_id: str, blocker_question: str | None) -> None:
    """Push a notification when a run pauses on the user.

    "One briefing message per day is law" also bounds needs_you pings: when
    other needs_you todos are already pending, this send REPLACES the
    single-blocker text with one message enumerating every pending blocker,
    instead of adding a second push alongside them.

    Best-effort: the transition is already persisted and broadcast over the
    websocket, so a delivery failure only delays the ping — log it, never raise.
    """
    doc = await todo_repository.get(todo_id, user_id=user_id)
    title = (doc.title if doc else None) or "your todo"
    body = (blocker_question or "").strip() or "GAIA needs a decision from you to continue."

    # The update that moved this todo to needs_you already landed, so it is
    # included here — count == 1 is the ordinary single-blocker case.
    pending = await todo_repository.list_open_gaia_by_status(
        user_id, statuses=[ExecutionStatus.NEEDS_YOU.value], limit=MAX_GAIA_TODOS_IN_FLIGHT
    )
    notification_title = f"GAIA needs you: {title}"
    notification_body = body
    action_url = f"/todos?todoId={todo_id}"
    action_label = "Open todo"
    if len(pending) > 1:
        notification_title = f"{len(pending)} things need your call"
        notification_body = "\n".join(_blocker_line(p) for p in pending)
        action_url = "/todos"
        action_label = "Open todos"

    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.AI_AGENT,
                type=NotificationType.WARNING,
                content=NotificationContent(
                    title=notification_title,
                    body=notification_body,
                    actions=[
                        NotificationAction(
                            type=ActionType.REDIRECT,
                            label=action_label,
                            style=ActionStyle.PRIMARY,
                            config=ActionConfig(
                                redirect=RedirectConfig(
                                    url=action_url,
                                    open_in_new_tab=False,
                                    close_notification=True,
                                )
                            ),
                        )
                    ],
                ),
                metadata={"kind": NOTIFICATION_KIND_TODO_NEEDS_YOU, "todo_id": todo_id},
            )
        )
    except Exception as e:
        log.warning("gaia_todo.needs_you_notification_failed", todo_id=todo_id, error=str(e))


async def block(todo_id: str, user_id: str, question: str) -> None:
    """Pause a queued/running todo on a decision only the user can make.

    The guarded ``→ needs_you`` entry point for the agent's ``block_todo`` tool;
    a proposed or terminal todo cannot be blocked.
    """
    question = question.strip()
    if not question:
        raise InvalidTransitionError("block requires a non-empty question")
    doc = await _get_gaia_todo(todo_id, user_id)
    current = doc.execution_status
    if current not in (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING):
        raise InvalidTransitionError(
            f"Only queued/running todos can be blocked (todo {todo_id} is {current!r})"
        )
    await mark_execution_status(
        todo_id, user_id, ExecutionStatus.NEEDS_YOU, blocker_question=question
    )
    await system_log(todo_id, user_id, "blocked", f"Run paused on: {question[:200]}")


async def answer(todo_id: str, user_id: str, answer_text: str, channel: str = "web") -> None:
    """Answer a blocked todo: record the reply and re-queue the run.

    The ONLY ``needs_you → queued`` path. The Q&A is appended to the notes
    facet so the next execution reads it naturally; the run resumes with
    whatever ``execution_intent`` it already had.
    """
    answer_text = answer_text.strip()
    if not answer_text:
        raise InvalidTransitionError("answer requires a non-empty reply")
    doc = await _require_status(todo_id, user_id, ExecutionStatus.NEEDS_YOU, "answered")
    now = datetime.now(UTC)
    question = doc.blocker_question or doc.error_message or "the open question"
    await append_facet(
        todo_id,
        user_id,
        FACET_NOTES,
        f"\n## User answer ({now.isoformat()})\nQ: {question}\nA: {answer_text}\n",
    )
    await todo_repository.update(
        todo_id,
        user_id=user_id,
        update=TodoUpdate(
            execution_status=ExecutionStatus.QUEUED,
            scheduled_at=now,
            blocker_question=None,
            error_message=None,
        ),
    )
    await schedule_execution(todo_id, now)
    await system_log(
        todo_id, user_id, "answered", f"User answered via {channel}: {answer_text[:200]}"
    )
    track(user_id, "todo_answered", {"todo_id": todo_id, "channel": channel})
    await _broadcast_status(user_id, todo_id, ExecutionStatus.QUEUED.value)
    schedule_gaia_tasks_sync(user_id)


async def retry(todo_id: str, user_id: str, channel: str = "web") -> None:
    """Re-run a failed todo: the only ``failed → queued`` path.

    Clears the failure state the execution loop reads (the ``failed`` label and
    ``error_message``) and resets ``gaia_retry_count`` so the re-run is a fresh
    execution episode, not a one-shot that fails immediately. ``gaia_user_retry_count``
    bounds how many times a human may retry a todo that keeps failing.
    """
    doc = await _require_status(todo_id, user_id, ExecutionStatus.FAILED, "retried")
    user_retries = doc.gaia_user_retry_count
    if user_retries >= MAX_GAIA_USER_RETRIES:
        raise InvalidTransitionError(
            f"This todo has already been retried {MAX_GAIA_USER_RETRIES} times and keeps "
            "failing. Edit it or hand it off before retrying again."
        )
    now = datetime.now(UTC)
    await todo_repository.retry_failed(todo_id, user_id, now=now, user_retry_count=user_retries + 1)
    await schedule_execution(todo_id, now)
    await system_log(todo_id, user_id, "retry", f"User retried after failure via {channel}")
    track(
        user_id,
        "todo_retried",
        {"todo_id": todo_id, "channel": channel, "attempt": user_retries + 1},
    )
    await _broadcast_status(user_id, todo_id, ExecutionStatus.QUEUED.value)
    schedule_gaia_tasks_sync(user_id)


async def expire_stale_proposals(user_id: str) -> list[str]:
    """Curation pass: expire proposals older than PROPOSAL_TTL_HOURS.

    Active upgrade pitches (``pitch_expires_at`` in the future) are exempt.
    Returns expired titles so the briefing can report the cleanup.
    """
    now = datetime.now(UTC)
    candidates = await todo_repository.list_expirable_proposals(
        user_id, before=now - timedelta(hours=PROPOSAL_TTL_HOURS), now=now
    )
    expired_titles: list[str] = []
    for doc in candidates:
        await todo_repository.update(
            doc.id,
            user_id=user_id,
            update=TodoUpdate(execution_status=ExecutionStatus.EXPIRED, completed=True),
        )
        await _record_rejection_signal(user_id, doc, "expired")
        track(user_id, "proposal_expired", {"todo_id": doc.id})
        expired_titles.append(doc.title or "untitled")
    if expired_titles:
        schedule_gaia_tasks_sync(user_id)
    return expired_titles


async def get_rejection_strikes_summary(user_id: str) -> str:
    """Rejected-kind steering block for prompt injection: counts, blocks, reasons.

    Derived from the todos collection (not memory recall) so the 3-strike rule
    cannot silently degrade. Each kind carries its strike count and the user's
    most recent verbatim dismissal reason so the agent can adapt (choose a
    different approach that honors the reason) rather than only avoid. Kinds at
    REJECTION_STRIKE_THRESHOLD+ are BLOCKED; sub-threshold kinds appear only when
    the user gave a reason worth learning from.
    """
    # Newest dismissal first, so the first reason seen per kind is the most recent
    # (expiries have no reason and no dismissed_at — they only add to the count).
    docs = await todo_repository.list_rejected_gaia(user_id)
    strikes: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for doc in docs:
        kind = derive_proposal_kind(doc)
        strikes[kind] = strikes.get(kind, 0) + 1
        reason = (doc.dismiss_reason or "").strip()
        if reason and kind not in reasons:
            reasons[kind] = reason

    lines: list[str] = []
    has_blocked = False
    for kind in sorted(strikes, key=lambda k: (-strikes[k], k)):
        count = strikes[kind]
        latest_reason = reasons.get(kind)
        if count >= REJECTION_STRIKE_THRESHOLD:
            has_blocked = True
            tag = f"{kind} ({count}x, BLOCKED)"
        elif latest_reason:
            tag = f"{kind} ({count}x)"
        else:
            # Sub-threshold with no stated reason teaches nothing — skip it.
            continue
        lines.append(f'- {tag}: user said "{latest_reason}"' if latest_reason else f"- {tag}")

    if not lines:
        return ""
    summary = "Rejected work — adapt, don't just avoid:\n" + "\n".join(lines)
    if has_blocked:
        summary += (
            f"\nBLOCKED kinds (rejected {REJECTION_STRIKE_THRESHOLD}+ times) must not "
            "be proposed again unless the user explicitly asks — use the reasons to "
            "pick a different approach that honors them."
        )
    return summary
