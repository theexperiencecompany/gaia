"""
OnboardingIntelligenceService — DAG-based onboarding pipeline.

Every node is an asyncio.Task that awaits its specific upstream futures and
emits its own stage event the moment it completes. The frontend consumes
these events independently and paces the visual reveal. There are no phases,
no progress percentages, and no false dependencies.

Critical path for the first reveal card (writing_style_ready):
  learn_writing_style (own 50-sent-email fetch + 1 Gemini call)

Critical path to COMPLETE:
  fetch_inbox → triage → workflows → first_message → seed → complete
              ↘       ↗
               writing_style (parallel root)

Holo card runs fully independently.
"""

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
import time
from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.memory.email_processor import (
    OnboardingFetchOptions,
    fetch_emails_for_onboarding,
)
from app.agents.prompts.onboarding_prompts import (
    FOCUS_TODOS_PROMPT,
    TRIAGE_TODOS_PROMPT,
    WORKFLOW_CREATION_PROMPT,
)
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.email import ONBOARDING_EMAIL_SCAN_LIMIT
from app.constants.log_tags import LogTag
from app.constants.onboarding import (
    EARLY_PHASE_POLL_INTERVAL_S,
    EARLY_PHASE_WAIT_TIMEOUT_S,
    NOT_SPECIFIED,
    OAUTH_INTEGRATION_NAME_BY_ID,
    TRIAGE_EARLY_THRESHOLD,
)
from app.constants.todos import ONBOARDING_TODO_LIMIT
from app.core.websocket_manager import websocket_manager
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.onboarding_models import (
    ClarifyAnswerRecord,
    CompletePayload,
    EmailSummary,
    InboxTriage,
    OnboardingTodoSource,
    OnboardingTodoSummary,
    OnboardingTriggerPayload,
    OnboardingWorkflowSummary,
    PersistedTriageSummary,
    SocialProfile,
    SocialProfilesReadyPayload,
    StagePayload,
    StatusTextPayload,
    TodosReadyPayload,
    TriageEmailSummary,
    TriageReadyPayload,
    WorkflowsReadyPayload,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
    WritingStyleReadyPayload,
)
from app.models.todo_models import Priority, TodoModel
from app.models.trigger_config import WorkflowTriggerSchema
from app.models.user_models import OnboardingPhase, UserDocument
from app.models.workflow_models import (
    CreateWorkflowRequest,
    SuggestedTrigger,
    TriggerConfig,
    TriggerType,
)
from app.services.composio.composio_service import get_composio_service
from app.services.onboarding import inbox_scan_cache
from app.services.onboarding.clarify_service import format_clarify_context
from app.services.onboarding.first_message_service import (
    default_first_message,
    generate_first_message,
)
from app.services.onboarding.inbox_triage_service import triage_inbox
from app.services.onboarding.post_onboarding_service import (
    save_personalization_data,
)
from app.services.onboarding.social_profile_service import (
    dedup_profiles_by_platform,
    extract_social_profiles_from_emails,
)
from app.services.onboarding.writing_style_service import learn_writing_style
from app.services.system_workflows.provisioner import provision_system_workflows
from app.services.todos.todo_service import TodoService
from app.services.workflow.generation_service import WorkflowGenerationService
from app.services.workflow.integration_requirements import (
    compute_missing_integrations,
    compute_required_integrations,
)
from app.services.workflow.service import WorkflowService
from app.utils.background_tasks import guard_task, spawn_background_task
from app.utils.profile_card import (
    generate_holo_card_content,
    generate_profile_card_design,
    get_user_metadata,
)
from app.utils.redis_utils import RedisPoolManager
from app.utils.seeding_utils import seed_onboarding_conversation
from shared.py.wide_events import log


class OnboardingStage(str, Enum):
    """Stages emitted over WebSocket during onboarding intelligence."""

    INBOX_SCANNING = "inbox_scanning"
    WRITING_STYLE_PROGRESS = "writing_style_progress"
    WRITING_STYLE_READY = "writing_style_ready"
    SOCIAL_PROFILES_READY = "social_profiles_ready"
    TRIAGE_ANALYZING = "triage_analyzing"
    TRIAGE_READY = "triage_ready"
    TODOS_CREATING = "todos_creating"
    TODOS_READY = "todos_ready"
    WORKFLOWS_CREATING = "workflows_creating"
    WORKFLOWS_READY = "workflows_ready"
    HOLO_READY = "holo_ready"
    COMPLETE = "complete"


async def _emit_stage(
    user_id: str,
    stage: OnboardingStage,
    payload: StagePayload | None = None,
) -> None:
    try:
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "onboarding_stage",
                "data": {"stage": stage.value, "payload": payload.to_wire() if payload else {}},
            },
        )
        status_text = payload.status_text if isinstance(payload, StatusTextPayload) else None
        if status_text:
            log.info(
                f"{LogTag.ONBOARDING} stage emitted with status",
                stage_value=stage.value,
                status_text=status_text,
            )
        else:
            log.info(f"{LogTag.ONBOARDING} stage emitted", stage_value=stage.value)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} Failed to emit stage",
            stage_value=stage.value,
            error=str(e),
            error_type=type(e).__name__,
        )


T = TypeVar("T")


async def _safe_run(name: str, coro: Awaitable[T], default: T) -> T:
    try:
        return await coro
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Node failed",
            name=name,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        return default


# Fallback cadence whenever a workflow has no usable suggested trigger.
_DEFAULT_WORKFLOW_CRON = "0 9 * * *"

_TODO_TITLE_MAX_CHARS = 80


def _truncate_title(title: str) -> str:
    """Trim a generated todo title to the display limit on a word boundary,
    falling back to a hard cut when the head has no usable break."""
    if len(title) <= _TODO_TITLE_MAX_CHARS:
        return title
    head = title[:_TODO_TITLE_MAX_CHARS]
    return head.rsplit(" ", 1)[0] or head


@dataclass
class InboxScanContext:
    """Shared state between the inbox fetch task and triage (which starts
    as soon as enough emails are buffered)."""

    # Raw Gmail message dicts straight off `fetch_emails_for_onboarding`; the key
    # set varies with the fetch format and the provider's casing (`labelIds` vs
    # `label_ids`), so this is a genuine external-boundary shape (item 8).
    emails: list[dict[str, Any]] = field(default_factory=list)
    first_batch_ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class OnboardingContext:
    """Shared per-user context threaded through the onboarding pipeline helpers."""

    user_id: str
    name: str
    profession: str = ""
    focus: str = ""
    has_gmail: bool = False
    user_timezone: str = "UTC"
    user_email: str | None = None
    triage: InboxTriage | None = None
    writing_style: WritingStyleProfile | None = None
    clarify_answers: list[ClarifyAnswerRecord] = field(default_factory=list)


class _TodoSpec(BaseModel):
    title: str = Field(description="What GAIA will do — under 80 chars, starts with a verb")
    description: str = Field(description="Context and what the output will be — 1-2 sentences")
    source_sender: str = Field(
        default="",
        description="The sender of the email this todo was created from. Empty string if not from a specific email.",
    )
    source_subject: str = Field(
        default="",
        description="The subject line of the email this todo was created from. Empty string if not from a specific email.",
    )


class _TodoListFromEmails(BaseModel):
    todos: list[_TodoSpec] = Field(description="List of exactly 3 GAIA-actionable todo items")


class _FocusTodoList(BaseModel):
    todos: list[str] = Field(
        description="List of 3 GAIA-actionable todo titles — each under 60 characters, starts with a verb"
    )


class _WorkflowSpec(BaseModel):
    title: str = Field(description="Workflow title — under 60 chars, starts with a verb or noun")
    description: str = Field(
        description="1-2 sentences: what triggers it, what it does, what output it produces"
    )
    categories: list[str] = Field(
        description=(
            "1-3 tool/integration categories this workflow uses. "
            "Pick only from: gmail, googlecalendar, slack, notion, github, linear, "
            "googledocs, googletasks, todoist, zoom, googlemeet, hubspot, airtable, "
            "trello, asana, clickup, twitter, linkedin, search, documents, todos, "
            "reminders, notifications, development. "
            "Only include categories that are genuinely relevant to the workflow."
        ),
        default_factory=list,
    )


class _WorkflowList(BaseModel):
    workflows: list[_WorkflowSpec] = Field(
        description="Exactly 4 workflow specs — no more, no fewer",
        min_length=4,
        max_length=4,
    )


async def _scan_then_enqueue_memory(user_id: str, ctx: InboxScanContext) -> None:
    """Run the visible inbox scan, then queue durable memory ingestion so it
    runs in parallel with triage/workflows and survives later failures."""
    await _run_inbox_scanning(user_id, ctx)
    try:
        pool = await RedisPoolManager.get_pool()
        await pool.enqueue_job("process_gmail_emails_to_memory", user_id)
        log.info(
            f"{LogTag.ONBOARDING} queued gmail->memory ingestion",
            user_id=user_id,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} failed to queue gmail->memory ingestion",
            user_id=user_id,
            error=str(e)[:200],
            error_type=type(e).__name__,
        )


def _start_gmail_branch(
    user_id: str,
) -> tuple[InboxScanContext, asyncio.Task[None]]:
    """Kick off the Gmail-only inbox scan + memory ingestion task and the system
    workflow provisioning task. Returns the shared inbox context and the
    provision future."""
    inbox_ctx = InboxScanContext()
    spawn_background_task(_scan_then_enqueue_memory(user_id, inbox_ctx))
    provision_future = asyncio.create_task(_run_provision_gmail(user_id))
    return inbox_ctx, provision_future


async def _persist_completion(
    user_id: str,
    conversation_id: str | None,
    provision_future: asyncio.Task[None] | None,
) -> None:
    """Write the unconditional end-of-pipeline phase transition and keep any
    still-running provision task alive past pipeline return."""
    await user_repository.set_pipeline_completion(
        user_id,
        phase=OnboardingPhase.PERSONALIZATION_COMPLETE,
        conversation_id=conversation_id or None,
    )

    if provision_future is not None and not provision_future.done():
        guard_task(provision_future)


async def _finalize_onboarding(
    ctx: OnboardingContext,
    *,
    todos: list[OnboardingTodoSummary],
    workflows: list[OnboardingWorkflowSummary],
    provision_future: asyncio.Task[None] | None,
    concurrent_tasks: Sequence[Awaitable[Any]] = (),
) -> str | None:
    """Shared pipeline tail for both onboarding shapes: generate the first
    message, persist it, seed the first conversation, persist completion, and
    emit COMPLETE. Returns the seeded conversation id (or None).

    `concurrent_tasks` run alongside conversation seeding — the full pipeline
    passes its profile/social/holo work here; the split path already ran that
    in its early phase and passes none.
    """
    t_msg = time.monotonic()
    first_message = await _safe_run(
        "first_message",
        generate_first_message(
            user_id=ctx.user_id,
            name=ctx.name,
            profession=ctx.profession,
            triage=ctx.triage,
            created_todos=todos,
            created_workflows=workflows,
            writing_style=ctx.writing_style,
            has_gmail=ctx.has_gmail,
            focus=ctx.focus,
            clarify_answers=ctx.clarify_answers,
        ),
        default=default_first_message(ctx.name),
    )
    log.info(
        f"{LogTag.ONBOARDING} first_message generated",
        user_id=ctx.user_id,
        message_chars=len(first_message),
        duration_s=round(time.monotonic() - t_msg, 2),
    )

    # Persist first_message before COMPLETE / the holo gather: the event triggers
    # a frontend fetch of /onboarding/personalization, which must not see null.
    await user_repository.set_first_message(ctx.user_id, first_message)

    seed_result, *_ = await asyncio.gather(_seed_conversation(ctx.user_id), *concurrent_tasks)
    conversation_id: str | None = seed_result

    # Unconditional end-of-pipeline transition: guarantees the user advances even
    # if the holo leg (which also writes this) failed.
    await _persist_completion(ctx.user_id, conversation_id, provision_future)
    await _emit_stage(
        ctx.user_id,
        OnboardingStage.COMPLETE,
        CompletePayload(conversation_id=conversation_id),
    )
    return conversation_id


async def _finish_early_phase(
    user_id: str,
    provision_future: asyncio.Task[None] | None,
) -> None:
    """Mark the early half done so the workflows-phase job can proceed, and
    keep any still-running provision task alive past pipeline return.
    `updated_at` is refreshed so the stuck-personalization cron's cutoff
    doesn't treat a user who is merely picking integrations as stale."""
    await user_repository.mark_early_intelligence_done(user_id)
    if provision_future is not None and not provision_future.done():
        guard_task(provision_future)


async def _social_then_holo(ctx: OnboardingContext, user: UserDocument) -> None:
    """Extract social profiles (Gmail-only) then build the holo card."""
    social_profiles: list[SocialProfile] = []
    if ctx.has_gmail:
        social_profiles = await _run_social_profiles_background(
            ctx.user_id, ctx.name, ctx.user_email
        )
    await _run_holo_card(
        ctx,
        user,
        social_profiles,
    )


async def process_onboarding_intelligence(user_id: str) -> None:
    """Main onboarding intelligence DAG. Called as an ARQ background task
    after POST /onboarding."""
    log.set(user={"id": user_id})
    pipeline_start = time.monotonic()
    log.info(
        f"{LogTag.ONBOARDING} pipeline start",
        user_id=user_id,
        phase="start",
    )

    # Emit an immediate status to both first-step stages before the Composio
    # check returns so the user sees activity right away regardless of branch.
    await asyncio.gather(
        _emit_stage(
            user_id,
            OnboardingStage.INBOX_SCANNING,
            StatusTextPayload(status_text="Getting things ready"),
        ),
        _emit_stage(
            user_id,
            OnboardingStage.TODOS_CREATING,
            StatusTextPayload(status_text="Getting things ready"),
        ),
    )

    user = await user_repository.get(user_id)
    if user is None:
        log.error(
            f"{LogTag.ONBOARDING} user not found",
            user_id=user_id,
            outcome="aborted",
            reason="user_not_found",
        )
        return

    onboarding = user.onboarding or {}
    name: str = user.name or "there"
    user_email: str | None = user.email
    profession: str = (onboarding.get("preferences") or {}).get("profession", "") or ""
    focus: str = onboarding.get("focus", "") or ""
    clarify_answers: list[ClarifyAnswerRecord] = onboarding.get("clarify_answers") or []
    selected_integrations: list[str] = onboarding.get("selected_integrations") or []
    # Two pipeline shapes, chosen at submission time by whether Gmail is connected:
    #
    #   split  (Gmail path): the frontend submits the moment Gmail connects, BEFORE
    #     the user has picked their other integrations. So this job runs only the
    #     expensive inbox work (scan/triage/todos/writing style/social) now, and
    #     defers workflow creation to a second job (process_onboarding_workflows_task)
    #     triggered by POST /onboarding/integrations. The inbox scan thus overlaps
    #     with the user's integration-picking time — that overlap is the whole point.
    #
    #   full  (no-Gmail path): the frontend waits for integration selection before
    #     submitting, so everything is known up front and there is no inbox to scan
    #     — nothing to overlap. Workflows run inline here, in this one job.
    #
    # Set once at submission time (defer_workflows) and never mutated, so a user
    # confirming integrations while this job is queued can't flip the branch mid-run.
    split_mode: bool = (onboarding.get("pipeline_mode") or "full") == "split"

    t_gmail_check = time.monotonic()
    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(["gmail"], user_id)
    has_gmail: bool = connection_status.get("gmail", False)
    log.info(
        f"{LogTag.ONBOARDING} gmail check",
        user_id=user_id,
        has_gmail=has_gmail,
        duration_s=round(time.monotonic() - t_gmail_check, 2),
    )
    log.info(
        f"{LogTag.ONBOARDING} inputs",
        user_id=user_id,
        has_gmail=has_gmail,
        profession_set=bool(profession),
        focus_set=bool(focus),
        branch="gmail" if has_gmail else "no_gmail",
    )

    inbox_ctx: InboxScanContext | None = None
    provision_future: asyncio.Task[None] | None = None

    if has_gmail:
        inbox_ctx, provision_future = _start_gmail_branch(user_id)

    writing_style_future: asyncio.Task[WritingStyleProfile | None] = asyncio.create_task(
        _run_writing_style(user_id, has_gmail, profession)
    )

    triage_future = asyncio.create_task(_run_triage(user_id, inbox_ctx, profession, focus))
    user_timezone: str = (user.timezone or "UTC").strip() or "UTC"
    base_ctx = OnboardingContext(
        user_id=user_id,
        name=name,
        profession=profession,
        focus=focus,
        has_gmail=has_gmail,
        user_timezone=user_timezone,
        user_email=user_email,
        clarify_answers=clarify_answers,
    )
    todos_future = asyncio.create_task(_run_todos(base_ctx, triage_future))

    workflows_future: asyncio.Task[list[OnboardingWorkflowSummary]] | None = None
    if not split_mode:

        async def _workflows_when_ready() -> list[OnboardingWorkflowSummary]:
            triage_res, style_res = await asyncio.gather(triage_future, writing_style_future)
            return await _run_workflows(
                replace(base_ctx, triage=triage_res, writing_style=style_res),
                selected_integrations,
            )

        workflows_future = asyncio.create_task(_workflows_when_ready())

    t_gather = time.monotonic()
    triage, todos, writing_style = await asyncio.gather(
        triage_future,
        todos_future,
        writing_style_future,
    )
    workflows: list[OnboardingWorkflowSummary] = await workflows_future if workflows_future else []
    log.info(
        f"{LogTag.ONBOARDING} critical_path gathered",
        user_id=user_id,
        phase="critical_path_gather",
        duration_s=round(time.monotonic() - t_gather, 2),
    )

    ctx = replace(base_ctx, triage=triage, writing_style=writing_style)
    triage_important_count = len(triage.important_emails) if triage else 0

    if split_mode:
        await asyncio.gather(
            _persist_profiles(user_id, writing_style, triage),
            _social_then_holo(ctx, user),
        )
        await _finish_early_phase(user_id, provision_future)
        log.info(
            f"{LogTag.ONBOARDING} early pipeline done — awaiting integration selection",
            user_id=user_id,
            phase="early_done",
            has_gmail=has_gmail,
            writing_style_learned=writing_style is not None,
            triage_important_count=triage_important_count,
            todos_count=len(todos),
            outcome="ok",
            duration_s=round(time.monotonic() - pipeline_start, 2),
        )
        return

    conversation_id = await _finalize_onboarding(
        ctx,
        todos=todos,
        workflows=workflows,
        provision_future=provision_future,
        concurrent_tasks=(
            _persist_profiles(user_id, writing_style, triage),
            _social_then_holo(ctx, user),
        ),
    )

    log.info(
        f"{LogTag.ONBOARDING} pipeline done",
        user_id=user_id,
        phase="done",
        has_gmail=has_gmail,
        writing_style_learned=writing_style is not None,
        triage_important_count=triage_important_count,
        todos_count=len(todos),
        workflows_count=len(workflows),
        conversation_seeded=conversation_id is not None,
        outcome=("ok" if conversation_id else "partial"),
        duration_s=round(time.monotonic() - pipeline_start, 2),
    )


async def _run_inbox_scanning(user_id: str, ctx: InboxScanContext) -> None:
    """Stream the inbox into ctx.emails. Sets first_batch_ready once ~100
    emails buffered so triage can start early; sets done when fetch completes."""
    t0 = time.monotonic()

    cached = await inbox_scan_cache.get(user_id, "metadata")
    if cached is not None:
        ctx.emails.extend(cached)
        ctx.first_batch_ready.set()
        ctx.done.set()
        await _emit_stage(
            user_id,
            OnboardingStage.INBOX_SCANNING,
            StatusTextPayload(status_text=f"Loaded {len(cached)} cached emails"),
        )
        log.info(
            f"{LogTag.ONBOARDING} inbox_scanning cache_hit",
            user_id=user_id,
            step="inbox_scanning",
            outcome="ok",
            emails_fetched=len(cached),
            cache_hit=True,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return

    await _emit_stage(
        user_id,
        OnboardingStage.INBOX_SCANNING,
        StatusTextPayload(status_text="Connecting to Gmail"),
    )

    async def _on_batch(current: int, latest_sender: str | None) -> None:
        if not ctx.first_batch_ready.is_set() and current >= TRIAGE_EARLY_THRESHOLD:
            ctx.first_batch_ready.set()
        status_text = (
            f"Fetched {current} emails — {latest_sender}"
            if latest_sender
            else f"Fetched {current} emails"
        )
        await _emit_stage(
            user_id,
            OnboardingStage.INBOX_SCANNING,
            StatusTextPayload(status_text=status_text),
        )

    fetch_ok = False
    try:
        await fetch_emails_for_onboarding(
            user_id,
            months=1,
            max_total=ONBOARDING_EMAIL_SCAN_LIMIT,
            on_batch=_on_batch,
            into=ctx.emails,
        )
        fetch_ok = True
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} inbox_scanning failed",
            user_id=user_id,
            step="inbox_scanning",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
    finally:
        ctx.first_batch_ready.set()
        ctx.done.set()
        if fetch_ok:
            await inbox_scan_cache.put(user_id, "metadata", list(ctx.emails))

    log.info(
        f"{LogTag.ONBOARDING} inbox_scanning done",
        user_id=user_id,
        step="inbox_scanning",
        outcome="ok" if fetch_ok else "failed",
        emails_fetched=len(ctx.emails),
        duration_s=round(time.monotonic() - t0, 2),
    )


async def _run_provision_gmail(user_id: str) -> None:
    t0 = time.monotonic()
    try:
        await provision_system_workflows(user_id, "gmail", "Gmail", notify=False)
        log.info(
            f"{LogTag.ONBOARDING} provision_gmail done",
            user_id=user_id,
            step="provision_gmail",
            outcome="ok",
            duration_s=round(time.monotonic() - t0, 2),
        )
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} provision_gmail failed",
            user_id=user_id,
            step="provision_gmail",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
        )


async def _run_writing_style(
    user_id: str,
    has_gmail: bool,
    profession: str,
) -> WritingStyleProfile | None:
    """Learn writing style from the user's last 50 sent emails. Gmail-only."""
    if not has_gmail:
        log.info(
            f"{LogTag.ONBOARDING} writing_style skipped",
            user_id=user_id,
            step="writing_style",
            outcome="skipped",
            skip_reason="no_gmail",
            duration_s=0.0,
        )
        return None

    async def _on_status(status_text: str) -> None:
        await _emit_stage(
            user_id,
            OnboardingStage.WRITING_STYLE_PROGRESS,
            StatusTextPayload(status_text=status_text),
        )

    t0 = time.monotonic()
    try:
        result = await learn_writing_style(user_id, profession=profession, on_status=_on_status)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} writing_style failed",
            user_id=user_id,
            step="writing_style",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        result = None

    log.info(
        f"{LogTag.ONBOARDING} writing_style done",
        user_id=user_id,
        step="writing_style",
        outcome="ok" if result else "empty",
        learned=result is not None,
        duration_s=round(time.monotonic() - t0, 2),
    )

    await _emit_stage(
        user_id,
        OnboardingStage.WRITING_STYLE_READY,
        WritingStyleReadyPayload(
            style_summary=result.summary if result and result.summary else None,
            example=result.example if result and result.example else None,
        ),
    )
    return result


async def _run_triage(
    user_id: str,
    inbox_ctx: InboxScanContext | None,
    profession: str,
    focus: str,
) -> InboxTriage | None:
    if inbox_ctx is None:
        log.info(
            f"{LogTag.ONBOARDING} triage skipped",
            user_id=user_id,
            step="triage",
            outcome="skipped",
            skip_reason="no_gmail",
        )
        return None
    await inbox_ctx.first_batch_ready.wait()
    emails = list(inbox_ctx.emails)
    if not emails:
        log.info(
            f"{LogTag.ONBOARDING} triage skipped",
            user_id=user_id,
            step="triage",
            outcome="skipped",
            skip_reason="no_emails",
        )
        return None

    await _emit_stage(
        user_id,
        OnboardingStage.TRIAGE_ANALYZING,
        StatusTextPayload(status_text=f"Analyzing {len(emails)} emails"),
    )

    t0 = time.monotonic()
    try:
        result = await triage_inbox(user_id, emails, profession=profession, focus=focus)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} triage failed",
            user_id=user_id,
            step="triage",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        result = None
    log.info(
        f"{LogTag.ONBOARDING} triage done",
        user_id=user_id,
        step="triage",
        outcome="ok" if result else "empty",
        emails_in=len(emails),
        important_count=len(result.important_emails) if result else 0,
        patterns_count=len(result.patterns) if result else 0,
        total_unread=result.total_unread if result else 0,
        duration_s=round(time.monotonic() - t0, 2),
    )

    if result and result.important_emails:
        n = len(result.important_emails)
        await _emit_stage(
            user_id,
            OnboardingStage.TRIAGE_ANALYZING,
            StatusTextPayload(status_text=f"Found {n} important thread{'s' if n != 1 else ''}"),
        )

    await _emit_stage(
        user_id,
        OnboardingStage.TRIAGE_READY,
        TriageReadyPayload(
            total_scanned=result.total_scanned if result else len(emails),
            total_unread=result.total_unread if result else 0,
            summary=result.summary if result else None,
            patterns=result.patterns if result else [],
            important_emails=_important_emails_for_client(result),
        ),
    )
    return result


def _important_emails_for_client(triage: InboxTriage | None) -> list[TriageEmailSummary]:
    """The top few important emails, projected onto the fields the client shows."""
    return [
        TriageEmailSummary(sender=e.sender, subject=e.subject, why_important=e.why_important)
        for e in (triage.important_emails[:5] if triage else [])
    ]


async def _run_social_profiles_background(
    user_id: str,
    user_name: str,
    user_email: str | None,
) -> list[SocialProfile]:
    """Fetch full email bodies, extract social profiles, persist, and emit
    SOCIAL_PROFILES_READY. Returns the deduped profiles."""
    t0 = time.monotonic()
    profiles: list[SocialProfile] = []
    try:
        emails = await inbox_scan_cache.get(user_id, "full")
        if emails is None:
            emails = await fetch_emails_for_onboarding(
                user_id,
                months=1,
                max_total=ONBOARDING_EMAIL_SCAN_LIMIT,
                options=OnboardingFetchOptions(fmt="full", include_sent=True),
            )
            # Only cache a non-empty fetch. A cached [] is not None, so every later
            # run — including the stuck-onboarding retry — would skip both the fetch
            # and the extraction and leave the user with no social profiles forever.
            if emails:
                await inbox_scan_cache.put(user_id, "full", emails)

        if emails:
            raw = await extract_social_profiles_from_emails(emails, user_name, user_email)
            raw_count = len(raw)
            profiles = dedup_profiles_by_platform(raw)
            await _persist_social_profiles(user_id, profiles)
            log.info(
                f"{LogTag.ONBOARDING} social_profiles done",
                user_id=user_id,
                step="social_profiles",
                outcome="ok",
                emails_in=len(emails),
                raw_count=raw_count,
                deduped_count=len(profiles),
                duration_s=round(time.monotonic() - t0, 2),
            )
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} social_profiles failed",
            user_id=user_id,
            step="social_profiles",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )

    await _emit_stage(
        user_id,
        OnboardingStage.SOCIAL_PROFILES_READY,
        SocialProfilesReadyPayload(profiles=profiles),
    )
    return profiles


async def _run_todos(
    ctx: OnboardingContext,
    triage_future: asyncio.Task[InboxTriage | None],
) -> list[OnboardingTodoSummary]:
    t0 = time.monotonic()
    todos: list[OnboardingTodoSummary] = []
    source = "none"
    try:
        if ctx.has_gmail:
            triage = await triage_future
            await _emit_stage(
                ctx.user_id,
                OnboardingStage.TODOS_CREATING,
                StatusTextPayload(status_text="Drafting todos from your inbox"),
            )
            if triage and triage.important_emails:
                source = "triage"
                todos = await _create_todos_from_triage(
                    ctx.user_id, triage, profession=ctx.profession, focus=ctx.focus
                )
            elif ctx.focus:
                source = "focus"
                todos = await _create_focus_todos(
                    ctx.user_id, ctx.name, ctx.profession, ctx.focus, ctx.clarify_answers
                )
        elif ctx.focus:
            source = "focus"
            await _emit_stage(
                ctx.user_id,
                OnboardingStage.TODOS_CREATING,
                StatusTextPayload(status_text="Drafting todos from your focus"),
            )
            todos = await _create_focus_todos(
                ctx.user_id, ctx.name, ctx.profession, ctx.focus, ctx.clarify_answers
            )
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} todos failed",
            user_id=ctx.user_id,
            step="todos",
            outcome="failed",
            source=source,
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        todos = []

    log.info(
        f"{LogTag.ONBOARDING} todos done",
        user_id=ctx.user_id,
        step="todos",
        outcome="ok" if todos else "empty",
        source=source,
        count=len(todos),
        duration_s=round(time.monotonic() - t0, 2),
    )
    n = len(todos)
    await _emit_stage(
        ctx.user_id,
        OnboardingStage.TODOS_READY,
        TodosReadyPayload(
            todos=todos,
            status_text=(f"Saved {n} todo{'s' if n != 1 else ''}" if n > 0 else "No todos to save"),
        ),
    )
    return todos


async def _run_workflows(
    ctx: OnboardingContext,
    selected_integrations: list[str] | None = None,
) -> list[OnboardingWorkflowSummary]:
    await _emit_stage(
        ctx.user_id,
        OnboardingStage.WORKFLOWS_CREATING,
        StatusTextPayload(status_text="Drafting workflow ideas"),
    )

    t0 = time.monotonic()
    try:
        workflows = await _create_onboarding_workflows(ctx, selected_integrations)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} workflows failed",
            user_id=ctx.user_id,
            step="workflows",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        workflows = []

    log.info(
        f"{LogTag.ONBOARDING} workflows done",
        user_id=ctx.user_id,
        step="workflows",
        outcome="ok" if workflows else "empty",
        count=len(workflows),
        has_triage=ctx.triage is not None,
        has_writing_style=ctx.writing_style is not None,
        duration_s=round(time.monotonic() - t0, 2),
    )

    try:
        workflow_ids = [w.id for w in workflows if w.id]
        if workflow_ids:
            await user_repository.set_suggested_workflows(ctx.user_id, workflow_ids)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} persist suggested_workflows failed",
            user_id=ctx.user_id,
            step="workflows",
            error=str(e)[:200],
            error_type=type(e).__name__,
        )

    n = len(workflows)
    await _emit_stage(
        ctx.user_id,
        OnboardingStage.WORKFLOWS_READY,
        WorkflowsReadyPayload(
            workflows=workflows,
            status_text=(
                f"Saved {n} workflow{'s' if n != 1 else ''}" if n > 0 else "No workflows to save"
            ),
        ),
    )
    return workflows


async def _run_holo_card(
    ctx: OnboardingContext,
    user: UserDocument,
    social_profiles: list[SocialProfile] | None = None,
) -> None:
    t0 = time.monotonic()
    try:
        context_parts: list[str] = []
        if ctx.triage:
            context_parts.append(f"Inbox summary: {ctx.triage.summary}")
            if ctx.triage.patterns:
                context_parts.append(f"Inbox patterns: {'; '.join(ctx.triage.patterns)}")
            if ctx.triage.important_emails:
                senders = ", ".join(e.sender for e in ctx.triage.important_emails[:5])
                context_parts.append(f"Key contacts: {senders}")
        if ctx.writing_style:
            context_parts.append(f"Writing style: {ctx.writing_style.summary}")
        if social_profiles:
            platforms = ", ".join(f"{p.platform}: {p.url}" for p in social_profiles)
            context_parts.append(f"Social profiles: {platforms}")
        if ctx.focus:
            context_parts.append(f"Current focus: {ctx.focus}")
        for answer in ctx.clarify_answers or []:
            value = (answer.get("value") or "").strip()
            if not value:
                continue
            kind = (answer.get("kind") or "context").strip() or "context"
            context_parts.append(f"{kind.capitalize()}: {value}")
        context_summary = "\n".join(context_parts)

        t_meta = time.monotonic()
        metadata = await get_user_metadata(ctx.user_id, user=user)
        meta_duration_s = round(time.monotonic() - t_meta, 2)
        card_design = generate_profile_card_design()
        t_phrase_bio = time.monotonic()
        phrase, user_bio, bio_status = await generate_holo_card_content(
            ctx.user_id, context_summary, user=user
        )
        phrase_bio_duration_s = round(time.monotonic() - t_phrase_bio, 2)
        t_save = time.monotonic()
        await save_personalization_data(
            ctx.user_id,
            card_design.house,
            phrase,
            user_bio,
            bio_status,
            [],
            metadata.account_number,
            metadata.member_since,
            card_design.overlay_color,
            card_design.overlay_opacity,
        )
        log.info(
            f"{LogTag.ONBOARDING} holo_card done",
            user_id=ctx.user_id,
            step="holo_card",
            outcome="ok",
            house=card_design.house,
            bio_status=str(bio_status),
            context_chars=len(context_summary),
            meta_duration_s=meta_duration_s,
            phrase_bio_duration_s=phrase_bio_duration_s,
            save_duration_s=round(time.monotonic() - t_save, 2),
            duration_s=round(time.monotonic() - t0, 2),
        )
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} holo_card failed",
            user_id=ctx.user_id,
            step="holo_card",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )

    await _emit_stage(ctx.user_id, OnboardingStage.HOLO_READY)


async def _seed_conversation(user_id: str) -> str | None:
    t0 = time.monotonic()
    try:
        cid = await seed_onboarding_conversation(user_id=user_id)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} seed_conversation failed",
            user_id=user_id,
            step="seed_conversation",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        return None
    log.info(
        f"{LogTag.ONBOARDING} seed_conversation done",
        user_id=user_id,
        step="seed_conversation",
        outcome="ok",
        conversation_id=cid,
        duration_s=round(time.monotonic() - t0, 2),
    )
    return cid


async def _persist_social_profiles(user_id: str, social_profiles: list[SocialProfile]) -> None:
    """Write auto-extracted profiles only if the user hasn't already confirmed
    them via POST /social-profiles."""
    if not social_profiles:
        return
    try:
        await user_repository.set_social_profiles_if_unset(user_id, social_profiles)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} persist social_profiles failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )


async def _persist_profiles(
    user_id: str,
    writing_style: WritingStyleProfile | None,
    triage: InboxTriage | None,
) -> None:
    """Persist writing style and triage summary. Social profiles are persisted
    separately by the background task in _run_social_profiles_background."""
    t0 = time.monotonic()
    triage_summary: PersistedTriageSummary | None = None
    if triage:
        triage_summary = PersistedTriageSummary(
            total_scanned=triage.total_scanned,
            total_unread=triage.total_unread,
            summary=triage.summary,
            patterns=triage.patterns,
            important_emails=_important_emails_for_client(triage),
        )

    if writing_style or triage:
        try:
            await user_repository.set_writing_style_and_triage(
                user_id,
                writing_style_summary=writing_style.summary if writing_style else None,
                writing_style_example=(writing_style.example if writing_style else None),
                triage_summary=triage_summary,
            )
        except Exception as e:
            log.error(
                f"{LogTag.ONBOARDING} persist update_fields failed",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )

    log.info(
        f"{LogTag.ONBOARDING} persist_profiles done",
        user_id=user_id,
        step="persist_profiles",
        writing_style_persisted=writing_style is not None,
        triage_persisted=triage is not None,
        duration_s=round(time.monotonic() - t0, 2),
    )


def _triage_from_doc(raw: object) -> InboxTriage | None:
    """Rebuild InboxTriage from the persisted onboarding.triage_summary subdoc."""
    if not isinstance(raw, dict):
        return None
    try:
        return InboxTriage(
            total_scanned=int(raw.get("total_scanned") or 0),
            total_unread=int(raw.get("total_unread") or 0),
            summary=str(raw.get("summary") or ""),
            patterns=[str(p) for p in raw.get("patterns") or []],
            important_emails=[
                EmailSummary(**e) for e in raw.get("important_emails") or [] if isinstance(e, dict)
            ],
        )
    except (TypeError, ValueError) as e:
        log.error(
            f"{LogTag.ONBOARDING} triage reconstruction failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        return None


def _writing_style_from_doc(raw: object) -> WritingStyleProfile | None:
    """Rebuild WritingStyleProfile from the persisted onboarding.writing_style subdoc."""
    if not isinstance(raw, dict):
        return None
    summary = str(raw.get("summary") or "").strip()
    example = raw.get("example")
    if not summary or not isinstance(example, dict):
        return None
    try:
        return WritingStyleProfile(
            summary=summary,
            example=WritingStyleExampleBlocks(**example),
            user_edited_summary=raw.get("user_edited_summary"),
        )
    except ValidationError as e:
        log.error(
            f"{LogTag.ONBOARDING} writing_style reconstruction failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        return None


async def _fetch_onboarding_todos(user_id: str) -> list[OnboardingTodoSummary]:
    todos = await todo_repository.list_onboarding_todos(user_id, limit=ONBOARDING_TODO_LIMIT)
    return [OnboardingTodoSummary(id=todo.id, title=todo.title or "") for todo in todos]


async def _wait_for_early_phase(user_id: str) -> bool:
    """Poll for the early-phase marker. Returns False on timeout — the caller
    proceeds with whatever is persisted (degraded workflow context, same
    fail-soft semantics as the full pipeline's None triage/style)."""
    deadline = time.monotonic() + EARLY_PHASE_WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        user = await user_repository.get(user_id)
        if user and (user.onboarding or {}).get("early_intelligence_done_at"):
            return True
        await asyncio.sleep(EARLY_PHASE_POLL_INTERVAL_S)
    log.warning(
        f"{LogTag.ONBOARDING} early phase marker timeout — proceeding with persisted data",
        user_id=user_id,
        timeout_s=EARLY_PHASE_WAIT_TIMEOUT_S,
    )
    return False


async def process_onboarding_workflows_phase(user_id: str) -> None:
    """Second half of the split pipeline: create the onboarding workflows from
    the user's selected integrations plus the persisted early-phase learnings,
    then first message -> seed conversation -> COMPLETE."""
    log.set(user={"id": user_id})
    pipeline_start = time.monotonic()
    log.info(f"{LogTag.ONBOARDING} workflows phase start", user_id=user_id, phase="start")

    await _wait_for_early_phase(user_id)

    user = await user_repository.get(user_id)
    if user is None:
        log.error(
            f"{LogTag.ONBOARDING} user not found",
            user_id=user_id,
            outcome="aborted",
            reason="user_not_found",
        )
        return

    onboarding = user.onboarding or {}
    name: str = user.name or "there"
    profession: str = (onboarding.get("preferences") or {}).get("profession", "") or ""
    focus: str = onboarding.get("focus", "") or ""
    clarify_answers: list[ClarifyAnswerRecord] = onboarding.get("clarify_answers") or []
    selected_integrations: list[str] = onboarding.get("selected_integrations") or []
    user_timezone: str = (user.timezone or "UTC").strip() or "UTC"

    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(["gmail"], user_id)
    has_gmail: bool = connection_status.get("gmail", False)

    triage = _triage_from_doc(onboarding.get("triage_summary"))
    writing_style = _writing_style_from_doc(onboarding.get("writing_style"))

    ctx = OnboardingContext(
        user_id=user_id,
        name=name,
        profession=profession,
        focus=focus,
        has_gmail=has_gmail,
        user_timezone=user_timezone,
        triage=triage,
        writing_style=writing_style,
        clarify_answers=clarify_answers,
    )

    # Idempotency: if a prior run of this phase was killed after creating some
    # workflows (leaving phase=PENDING so the stuck cron re-enqueues it), drop
    # those stale suggestions before regenerating so the retry replaces them
    # instead of doubling up. Onboarding workflows are created deactivated —
    # no Composio triggers or scheduled jobs to unwind — so a direct delete is safe.
    prior_workflow_ids: list[str] = onboarding.get("suggested_workflows") or []
    if prior_workflow_ids:
        deleted = await workflow_repository.delete_many_for_user(prior_workflow_ids, user_id)
        log.info(
            f"{LogTag.ONBOARDING} workflows phase retry — purged stale "
            f"suggested workflows before regenerating",
            user_id=user_id,
            deleted=deleted,
        )

    workflows = await _run_workflows(ctx, selected_integrations)

    todos = await _fetch_onboarding_todos(user_id)
    conversation_id = await _finalize_onboarding(
        ctx,
        todos=todos,
        workflows=workflows,
        provision_future=None,
    )

    log.info(
        f"{LogTag.ONBOARDING} workflows phase done",
        user_id=user_id,
        phase="done",
        has_gmail=has_gmail,
        has_triage=triage is not None,
        has_writing_style=writing_style is not None,
        workflows_count=len(workflows),
        conversation_seeded=conversation_id is not None,
        outcome=("ok" if conversation_id else "partial"),
        duration_s=round(time.monotonic() - pipeline_start, 2),
    )


async def _create_focus_todos(
    user_id: str,
    name: str,
    profession: str,
    focus: str,
    clarify_answers: list[ClarifyAnswerRecord] | None = None,
) -> list[OnboardingTodoSummary]:
    """Create GAIA-actionable todos from the user's stated focus via LLM."""
    t0 = time.monotonic()
    prompt = FOCUS_TODOS_PROMPT.format(
        name=name,
        profession=profession,
        focus=focus,
        clarify_context=format_clarify_context(clarify_answers),
        format_instructions=f"Return a JSON object with a 'todos' key containing a list of {ONBOARDING_TODO_LIMIT} todo title strings.",
    )

    try:
        t_llm = time.monotonic()
        parsed: _FocusTodoList = await ainvoke_structured(
            _FocusTodoList,
            prompt,
            label="onboarding_focus_todos",
            config=metered_config(user_id),
        )
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        async def _create_one(title: str) -> OnboardingTodoSummary | None:
            try:
                safe_title = _truncate_title(title)
                todo = TodoModel(
                    title=safe_title,
                    description=f"Created from your focus: {focus[:200]}",
                    labels=["onboarding"],
                    priority=Priority.MEDIUM,
                    project_id=None,
                )
                result = await TodoService.create_todo(todo, user_id)
                return OnboardingTodoSummary(id=str(result.id), title=safe_title)
            except Exception as e:
                log.warning(
                    f"{LogTag.ONBOARDING} focus todo create failed",
                    user_id=user_id,
                    step="todos_focus_create_one",
                    title=title[:60],
                    error=str(e)[:200],
                    error_type=type(e).__name__,
                )
                return None

        t_create = time.monotonic()
        results = await asyncio.gather(
            *[_create_one(t) for t in parsed.todos[:ONBOARDING_TODO_LIMIT]]
        )
        created = [r for r in results if r is not None]
        log.info(
            f"{LogTag.ONBOARDING} focus_todos done",
            user_id=user_id,
            step="todos_focus",
            outcome="ok",
            specs_count=len(parsed.todos[:ONBOARDING_TODO_LIMIT]),
            created_count=len(created),
            llm_duration_s=llm_duration_s,
            create_duration_s=round(time.monotonic() - t_create, 2),
            duration_s=round(time.monotonic() - t0, 2),
        )
        return created

    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} focus_todos failed",
            user_id=user_id,
            step="todos_focus",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return []


async def _create_todos_from_triage(
    user_id: str,
    triage: InboxTriage,
    profession: str = "",
    focus: str = "",
) -> list[OnboardingTodoSummary]:
    real_emails = triage.important_emails[:8]
    emails_context = "\n".join(
        f"- From: {e.sender} | Subject: {e.subject} | Why important: {e.why_important}"
        for e in real_emails
    )
    real_senders = {e.sender for e in real_emails}
    real_subjects = {e.subject for e in real_emails}

    prompt = TRIAGE_TODOS_PROMPT.format(
        emails_context=emails_context,
        profession=profession or NOT_SPECIFIED,
        focus=focus or NOT_SPECIFIED,
        format_instructions="Return a JSON object with a 'todos' key containing a list of todo objects, each with 'title', 'description', 'source_sender', and 'source_subject'.",
    )

    t0 = time.monotonic()
    try:
        t_llm = time.monotonic()
        parsed: _TodoListFromEmails = await ainvoke_structured(
            _TodoListFromEmails,
            prompt,
            label="onboarding_todos_from_emails",
            config=metered_config(user_id),
        )
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        async def _create_one(spec: _TodoSpec) -> OnboardingTodoSummary | None:
            try:
                safe_title = _truncate_title(spec.title)
                todo = TodoModel(
                    title=safe_title,
                    description=spec.description[:500],
                    labels=["onboarding"],
                    priority=Priority.MEDIUM,
                    project_id=None,
                )
                result = await TodoService.create_todo(todo, user_id)
                created = OnboardingTodoSummary(id=str(result.id), title=safe_title)
                sender_ok = spec.source_sender and spec.source_sender in real_senders
                subject_ok = spec.source_subject and spec.source_subject in real_subjects
                if sender_ok and subject_ok:
                    created.source_email = OnboardingTodoSource(
                        sender=spec.source_sender,
                        subject=spec.source_subject,
                    )
                elif spec.source_sender or spec.source_subject:
                    log.warning(
                        f"{LogTag.ONBOARDING} Dropped hallucinated source_email",
                        source_sender=spec.source_sender,
                        source_subject=spec.source_subject,
                    )
                return created
            except Exception as e:
                log.warning(
                    f"{LogTag.ONBOARDING} Failed to create todo",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return None

        t_create = time.monotonic()
        results = await asyncio.gather(
            *[_create_one(s) for s in parsed.todos[:ONBOARDING_TODO_LIMIT]]
        )
        created = [r for r in results if r is not None]
        log.info(
            f"{LogTag.ONBOARDING} triage_todos done",
            user_id=user_id,
            step="todos_triage",
            outcome="ok",
            specs_count=len(parsed.todos[:ONBOARDING_TODO_LIMIT]),
            created_count=len(created),
            llm_duration_s=llm_duration_s,
            create_duration_s=round(time.monotonic() - t_create, 2),
            duration_s=round(time.monotonic() - t0, 2),
        )
        return created

    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} triage_todos failed",
            user_id=user_id,
            step="todos_triage",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return []


def _build_trigger_config_from_suggestion(
    suggestion: SuggestedTrigger | None,
) -> TriggerConfig:
    """Map the generator's suggested trigger into a real TriggerConfig."""
    if suggestion is None:
        return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON)

    s_type = suggestion.type.lower()
    if s_type == "manual":
        return TriggerConfig(type=TriggerType.MANUAL)

    if s_type == "schedule":
        # Strip before the fallback: a whitespace-only cron is truthy, so testing it
        # first left an empty expression that fails TriggerConfig validation and
        # loses the whole workflow in the caller's except.
        cron = (suggestion.cron_expression or "").strip() or _DEFAULT_WORKFLOW_CRON
        return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=cron)

    if s_type == "integration":
        slug = suggestion.trigger_name
        schema = _find_workflow_trigger_schema(slug) if slug else None
        if not schema:
            return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON)

        # Triggers with config fields need typed trigger_data we can't build
        # generically — fall back to a schedule for those.
        if schema.config_schema:
            return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON)

        return TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name=slug,
        )

    return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON)


def _find_workflow_trigger_schema(slug: str) -> WorkflowTriggerSchema | None:
    for integration in OAUTH_INTEGRATIONS:
        for tc in integration.associated_triggers or []:
            if tc.workflow_trigger_schema and tc.workflow_trigger_schema.slug == slug:
                return tc.workflow_trigger_schema
    return None


def _serialize_trigger_for_payload(trigger_config: TriggerConfig) -> OnboardingTriggerPayload:
    # `or None` on each optional: the payload model drops None fields on the wire,
    # so an empty string stays absent exactly as it was when this hand-built a dict
    # behind `if trigger_config.<field>:` guards.
    return OnboardingTriggerPayload(
        type=trigger_config.type,
        cron_expression=trigger_config.cron_expression or None,
        timezone=trigger_config.timezone or None,
        trigger_name=trigger_config.trigger_name or None,
    )


def _build_workflow_prompt_context(
    ctx: OnboardingContext,
    selected_integrations: list[str] | None = None,
) -> str:
    """Render the workflow-creation prompt from the user's onboarding context."""
    triage = ctx.triage
    inbox_patterns = (
        "; ".join(triage.patterns[:3]) if triage and triage.patterns else "no patterns detected"
    )
    email_senders_summary = (
        ", ".join(e.sender for e in triage.important_emails[:5])
        if triage and triage.important_emails
        else "no email data"
    )
    writing_style_summary = ctx.writing_style.summary[:150] if ctx.writing_style else "not analyzed"

    friendly = [
        OAUTH_INTEGRATION_NAME_BY_ID[s]
        for s in (selected_integrations or [])
        if s in OAUTH_INTEGRATION_NAME_BY_ID
    ]
    if friendly:
        selected_integrations_section = (
            "Preferred integrations (anchor at least half of the workflows to these tools):\n"
            + ", ".join(friendly)
            + "\n\n"
        )
    else:
        selected_integrations_section = ""

    return WORKFLOW_CREATION_PROMPT.format(
        profession=ctx.profession or "professional",
        focus=ctx.focus or NOT_SPECIFIED,
        clarify_context=format_clarify_context(ctx.clarify_answers),
        selected_integrations_section=selected_integrations_section,
        has_gmail=ctx.has_gmail,
        inbox_patterns=inbox_patterns,
        email_senders_summary=email_senders_summary,
        writing_style_summary=writing_style_summary,
    )


# Retries for the workflow-spec generation LLM call before giving up.
_WORKFLOW_SPEC_MAX_ATTEMPTS = 3


async def _generate_workflow_specs(user_id: str, prompt: str) -> _WorkflowList:
    """Invoke the LLM up to ``_WORKFLOW_SPEC_MAX_ATTEMPTS`` times, raising if every
    attempt fails.

    `_WorkflowList` pins the list to exactly 4 specs, so a wrong count arrives here
    as a ValidationError and is retried like any other failure — there is no
    separate count check to make.
    """
    last_error: Exception | None = None
    for attempt in range(_WORKFLOW_SPEC_MAX_ATTEMPTS):
        try:
            return await ainvoke_structured(
                _WorkflowList,
                prompt,
                label="onboarding_workflow_suggestions",
                config=metered_config(user_id),
            )
        except Exception as e:
            last_error = e
            log.warning(
                f"{LogTag.ONBOARDING} workflow specs llm failed, retrying",
                user_id=user_id,
                step="workflows_specs_llm",
                attempt=attempt,
                error=str(e)[:200],
            )

    raise RuntimeError(
        f"Workflow spec generation failed after {_WORKFLOW_SPEC_MAX_ATTEMPTS} attempts"
    ) from last_error


def _workflow_integration_ids(
    spec: _WorkflowSpec,
    selected_integrations: list[str] | None,
) -> list[str] | None:
    """The integrations THIS workflow depends on, not the whole onboarding selection.

    The spec's own categories name the tools it uses, so they describe the
    dependency accurately; writing the user's full selection onto every workflow
    would claim Slack on a Notion-only workflow. Non-integration categories
    (todos, reminders, ...) are dropped downstream by
    filter_existing_integration_ids. Falls back to the selection when the model
    named no categories, so step generation still has something to ground on.
    """
    from_spec = list(dict.fromkeys(spec.categories))
    return from_spec or (selected_integrations or None)


async def _build_one_workflow(
    user_id: str,
    idx: int,
    spec: _WorkflowSpec,
    user_timezone: str,
    selected_integrations: list[str] | None = None,
) -> OnboardingWorkflowSummary | None:
    """Generate the prompt + trigger for a single spec and persist the workflow."""
    t_spec = time.monotonic()
    try:
        t_prompt = time.monotonic()
        gen_result = await WorkflowGenerationService.generate_workflow_prompt(
            title=spec.title,
            description=spec.description,
            user_id=user_id,
        )
        prompt_duration_s = round(time.monotonic() - t_prompt, 2)
        workflow_prompt = (gen_result.get("prompt") or spec.description).strip()
        trigger_config = _build_trigger_config_from_suggestion(gen_result.get("suggested_trigger"))

        request = CreateWorkflowRequest(
            title=spec.title,
            description=spec.description,
            prompt=workflow_prompt,
            trigger_config=trigger_config,
            generate_immediately=True,
            integration_ids=_workflow_integration_ids(spec, selected_integrations),
        )
        t_create = time.monotonic()
        workflow = await WorkflowService.create_workflow(
            request, user_id, user_timezone=user_timezone
        )
        create_duration_s = round(time.monotonic() - t_create, 2)
        log.info(
            f"{LogTag.ONBOARDING} workflow spec done",
            user_id=user_id,
            step="workflows_spec",
            spec_index=idx,
            spec_title=spec.title[:60],
            trigger_type=trigger_config.type.value,
            workflow_id=str(workflow.id),
            prompt_duration_s=prompt_duration_s,
            create_duration_s=create_duration_s,
            duration_s=round(time.monotonic() - t_spec, 2),
        )
        # Surface step + trigger integrations the user hasn't connected so the
        # onboarding cards show the same missing-integration warning as the app.
        required = compute_required_integrations(workflow.steps, workflow.trigger_config)
        missing = await compute_missing_integrations(required, user_id)
        return OnboardingWorkflowSummary(
            id=str(workflow.id),
            title=spec.title,
            description=spec.description,
            categories=spec.categories,
            trigger=_serialize_trigger_for_payload(workflow.trigger_config),
            missing_integrations=missing,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} workflow spec failed",
            user_id=user_id,
            step="workflows_spec",
            spec_index=idx,
            spec_title=spec.title[:60],
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t_spec, 2),
        )
        return None


async def _create_onboarding_workflows(
    ctx: OnboardingContext,
    selected_integrations: list[str] | None = None,
) -> list[OnboardingWorkflowSummary]:
    """Create 4 LLM-generated workflows tailored to the user's context."""
    # Keep only known integration ids (request-backed input), de-duped and
    # order-preserving. Include Gmail when connected and not already listed.
    effective_integrations: list[str] = [
        s for s in dict.fromkeys(selected_integrations or []) if s in OAUTH_INTEGRATION_NAME_BY_ID
    ]
    if ctx.has_gmail and "gmail" not in effective_integrations:
        effective_integrations.append("gmail")

    prompt = _build_workflow_prompt_context(ctx, effective_integrations or None)

    t0 = time.monotonic()
    try:
        t_specs_llm = time.monotonic()
        parsed = await _generate_workflow_specs(ctx.user_id, prompt)
        specs_llm_duration_s = round(time.monotonic() - t_specs_llm, 2)
        log.info(
            f"{LogTag.ONBOARDING} workflow specs generated",
            user_id=ctx.user_id,
            step="workflows_specs_llm",
            specs_count=len(parsed.workflows),
            llm_duration_s=specs_llm_duration_s,
        )
        specs_total = len(parsed.workflows)

        results = await asyncio.gather(
            *[
                _build_one_workflow(
                    ctx.user_id, idx, spec, ctx.user_timezone, effective_integrations or None
                )
                for idx, spec in enumerate(parsed.workflows)
            ]
        )
        created = [r for r in results if r is not None]
        specs_failed = specs_total - len(created)
        log.info(
            f"{LogTag.ONBOARDING} workflows specs done",
            user_id=ctx.user_id,
            step="workflows_specs",
            specs_total=specs_total,
            specs_created=len(created),
            specs_failed=specs_failed,
            fallback_used=False,
            specs_llm_duration_s=specs_llm_duration_s,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return created
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} workflow LLM failed, using fallback",
            user_id=ctx.user_id,
            step="workflows",
            error=str(e)[:200],
            error_type=type(e).__name__,
            fallback_used=True,
        )
        return await _create_fallback_workflow(
            ctx.user_id, ctx.focus, ctx.user_timezone, effective_integrations or None
        )


async def _create_fallback_workflow(
    user_id: str,
    focus: str = "",
    user_timezone: str = "UTC",
    integration_ids: list[str] | None = None,
) -> list[OnboardingWorkflowSummary]:
    title = "Daily Briefing"
    description = (
        f"Every morning, summarize unread emails by priority, today's meetings, and open todos. "
        f"Focus: {focus[:100]}."
        if focus
        else "Every morning at 9am, summarize unread emails by priority, today's meetings, and open todos."
    )
    try:
        trigger_config = TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )
        request = CreateWorkflowRequest(
            title=title,
            description=description,
            prompt=description,
            trigger_config=trigger_config,
            generate_immediately=True,
            integration_ids=integration_ids,
        )
        workflow = await WorkflowService.create_workflow(
            request, user_id, user_timezone=user_timezone
        )
        return [
            OnboardingWorkflowSummary(
                id=str(workflow.id),
                title=title,
                description=description,
                categories=[],
                trigger=_serialize_trigger_for_payload(workflow.trigger_config),
            )
        ]
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} Fallback workflow creation failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return []
