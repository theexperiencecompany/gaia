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
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

from app.agents.llm.client import ainvoke_structured
from app.agents.memory.email_processor import fetch_emails_for_onboarding
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
    ONBOARDING_DEFAULT_FIRST_MESSAGE,
    TRIAGE_EARLY_THRESHOLD,
)
from app.constants.todos import ONBOARDING_TODO_LIMIT
from app.core.websocket_manager import websocket_manager
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.onboarding_models import (
    EmailSummary,
    InboxTriage,
    SocialProfile,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
)
from app.models.todo_models import Priority, TodoModel
from app.models.user_models import OnboardingPhase
from app.models.workflow_models import CreateWorkflowRequest, TriggerConfig, TriggerType
from app.services.composio.composio_service import get_composio_service
from app.services.onboarding import inbox_scan_cache
from app.services.onboarding.clarify_service import format_clarify_context
from app.services.onboarding.first_message_service import generate_first_message
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
    payload: dict | None = None,
) -> None:
    try:
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "onboarding_stage",
                "data": {"stage": stage.value, "payload": payload or {}},
            },
        )
        status_text = (payload or {}).get("status_text")
        if status_text:
            log.info(f"{LogTag.ONBOARDING} stage {stage.value} — {status_text}")
        else:
            log.info(f"{LogTag.ONBOARDING} stage {stage.value}")
    except Exception as e:
        log.warning(f"{LogTag.ONBOARDING} Failed to emit stage {stage.value}: {e}")


T = TypeVar("T")


async def _safe_run(name: str, coro: Awaitable[T], default: T) -> T:
    try:
        return await coro
    except Exception as e:
        log.error(f"{LogTag.ONBOARDING} Node '{name}' failed: {e}", exc_info=True)
        return default


# Module-level set prevents GC of fire-and-forget tasks
_background_tasks: set[asyncio.Task] = set()


@dataclass
class InboxScanContext:
    """Shared state between the inbox fetch task and triage (which starts
    as soon as enough emails are buffered)."""

    emails: list[dict] = field(default_factory=list)
    first_batch_ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


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
    scan_task = asyncio.create_task(_scan_then_enqueue_memory(user_id, inbox_ctx))
    _background_tasks.add(scan_task)
    scan_task.add_done_callback(_background_tasks.discard)
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
        _background_tasks.add(provision_future)
        provision_future.add_done_callback(_background_tasks.discard)


async def _finalize_onboarding(
    user_id: str,
    *,
    name: str,
    profession: str,
    triage: InboxTriage | None,
    todos: list[dict],
    workflows: list[dict],
    writing_style: WritingStyleProfile | None,
    has_gmail: bool,
    focus: str,
    clarify_answers: list[dict],
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
            user_id=user_id,
            name=name,
            profession=profession,
            triage=triage,
            created_todos=todos,
            created_workflows=workflows,
            writing_style=writing_style,
            has_gmail=has_gmail,
            focus=focus,
            clarify_answers=clarify_answers,
        ),
        default=ONBOARDING_DEFAULT_FIRST_MESSAGE,
    )
    log.info(
        f"{LogTag.ONBOARDING} first_message generated",
        user_id=user_id,
        message_chars=len(first_message),
        duration_s=round(time.monotonic() - t_msg, 2),
    )

    # Persist first_message before COMPLETE / the holo gather: the event triggers
    # a frontend fetch of /onboarding/personalization, which must not see null.
    await user_repository.set_first_message(user_id, first_message)

    seed_result, *_ = await asyncio.gather(_seed_conversation(user_id), *concurrent_tasks)
    conversation_id: str | None = seed_result

    # Unconditional end-of-pipeline transition: guarantees the user advances even
    # if the holo leg (which also writes this) failed.
    await _persist_completion(user_id, conversation_id, provision_future)
    await _emit_stage(
        user_id,
        OnboardingStage.COMPLETE,
        {"conversation_id": conversation_id},
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
        _background_tasks.add(provision_future)
        provision_future.add_done_callback(_background_tasks.discard)


async def _social_then_holo(
    user_id: str,
    name: str,
    user_email: str | None,
    user_doc: dict,
    focus: str,
    triage: InboxTriage | None,
    writing_style: WritingStyleProfile | None,
    clarify_answers: list[dict],
    has_gmail: bool,
) -> None:
    """Extract social profiles (Gmail-only) then build the holo card."""
    social_profiles: list[SocialProfile] = []
    if has_gmail:
        social_profiles = await _run_social_profiles_background(user_id, name, user_email)
    await _run_holo_card(
        user_id,
        user_doc,
        focus,
        triage,
        writing_style,
        social_profiles,
        clarify_answers,
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
            {"status_text": "Getting things ready"},
        ),
        _emit_stage(
            user_id,
            OnboardingStage.TODOS_CREATING,
            {"status_text": "Getting things ready"},
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
    # Raw-style dict for the downstream holo/metadata helpers that still read a dict.
    user_doc = user.model_dump() | {"_id": user.id, "user_id": user.id}
    profession: str = (onboarding.get("preferences") or {}).get("profession", "") or ""
    focus: str = onboarding.get("focus", "") or ""
    clarify_answers: list[dict] = onboarding.get("clarify_answers") or []
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
    todos_future = asyncio.create_task(
        _run_todos(
            user_id,
            name,
            profession,
            focus,
            has_gmail,
            triage_future,
            clarify_answers,
        )
    )
    user_timezone: str = (user_doc.get("timezone") or "UTC").strip() or "UTC"

    workflows_future: asyncio.Task[list[dict]] | None = None
    if not split_mode:

        async def _workflows_when_ready() -> list[dict]:
            triage_res, style_res = await asyncio.gather(triage_future, writing_style_future)
            return await _run_workflows(
                user_id,
                profession,
                has_gmail,
                focus,
                user_timezone,
                triage_res,
                style_res,
                clarify_answers,
                selected_integrations,
            )

        workflows_future = asyncio.create_task(_workflows_when_ready())

    t_gather = time.monotonic()
    triage, todos, writing_style = await asyncio.gather(
        triage_future,
        todos_future,
        writing_style_future,
    )
    workflows: list[dict] = await workflows_future if workflows_future else []
    log.info(
        f"{LogTag.ONBOARDING} critical_path gathered",
        user_id=user_id,
        phase="critical_path_gather",
        duration_s=round(time.monotonic() - t_gather, 2),
    )

    triage_important_count = len(triage.important_emails) if triage else 0

    if split_mode:
        await asyncio.gather(
            _persist_profiles(user_id, writing_style, triage),
            _social_then_holo(
                user_id=user_id,
                name=name,
                user_email=user_email,
                user_doc=user_doc,
                focus=focus,
                triage=triage,
                writing_style=writing_style,
                clarify_answers=clarify_answers,
                has_gmail=has_gmail,
            ),
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
        user_id,
        name=name,
        profession=profession,
        triage=triage,
        todos=todos,
        workflows=workflows,
        writing_style=writing_style,
        has_gmail=has_gmail,
        focus=focus,
        clarify_answers=clarify_answers,
        provision_future=provision_future,
        concurrent_tasks=(
            _persist_profiles(user_id, writing_style, triage),
            _social_then_holo(
                user_id=user_id,
                name=name,
                user_email=user_email,
                user_doc=user_doc,
                focus=focus,
                triage=triage,
                writing_style=writing_style,
                clarify_answers=clarify_answers,
                has_gmail=has_gmail,
            ),
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
            {"status_text": f"Loaded {len(cached)} cached emails"},
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
        {"status_text": "Connecting to Gmail"},
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
            {"status_text": status_text},
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
        outcome="ok",
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
            {"status_text": status_text},
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
        {
            "style_summary": result.summary if result and result.summary else None,
            "example": result.example.model_dump() if result and result.example else None,
        },
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
        {"status_text": f"Analyzing {len(emails)} emails"},
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
            {
                "status_text": (f"Found {n} important thread{'s' if n != 1 else ''}"),
            },
        )

    await _emit_stage(
        user_id,
        OnboardingStage.TRIAGE_READY,
        {
            "total_scanned": result.total_scanned if result else len(emails),
            "total_unread": result.total_unread if result else 0,
            "summary": result.summary if result else None,
            "patterns": result.patterns if result else [],
            "important_emails": [
                {
                    "sender": e.sender,
                    "subject": e.subject,
                    "why_important": e.why_important,
                }
                for e in (result.important_emails[:5] if result else [])
            ],
        },
    )
    return result


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
                fmt="full",
            )
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
        {"profiles": [{"platform": p.platform, "url": p.url} for p in profiles]},
    )
    return profiles


async def _run_todos(
    user_id: str,
    name: str,
    profession: str,
    focus: str,
    has_gmail: bool,
    triage_future: asyncio.Task[InboxTriage | None],
    clarify_answers: list[dict] | None = None,
) -> list[dict]:
    t0 = time.monotonic()
    todos: list[dict] = []
    source = "none"
    try:
        if has_gmail:
            triage = await triage_future
            await _emit_stage(
                user_id,
                OnboardingStage.TODOS_CREATING,
                {"status_text": "Drafting todos from your inbox"},
            )
            if triage and triage.important_emails:
                source = "triage"
                todos = await _create_todos_from_triage(
                    user_id, triage, profession=profession, focus=focus
                )
            elif focus:
                source = "focus"
                todos = await _create_focus_todos(user_id, name, profession, focus, clarify_answers)
        elif focus:
            source = "focus"
            await _emit_stage(
                user_id,
                OnboardingStage.TODOS_CREATING,
                {"status_text": "Drafting todos from your focus"},
            )
            todos = await _create_focus_todos(user_id, name, profession, focus, clarify_answers)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} todos failed",
            user_id=user_id,
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
        user_id=user_id,
        step="todos",
        outcome="ok" if todos else "empty",
        source=source,
        count=len(todos),
        duration_s=round(time.monotonic() - t0, 2),
    )
    n = len(todos)
    await _emit_stage(
        user_id,
        OnboardingStage.TODOS_READY,
        {
            "todos": todos,
            "status_text": (
                f"Saved {n} todo{'s' if n != 1 else ''}" if n > 0 else "No todos to save"
            ),
        },
    )
    return todos


async def _run_workflows(
    user_id: str,
    profession: str,
    has_gmail: bool,
    focus: str,
    user_timezone: str,
    triage: InboxTriage | None,
    writing_style: WritingStyleProfile | None,
    clarify_answers: list[dict] | None = None,
    selected_integrations: list[str] | None = None,
) -> list[dict]:
    await _emit_stage(
        user_id,
        OnboardingStage.WORKFLOWS_CREATING,
        {"status_text": "Drafting workflow ideas"},
    )

    t0 = time.monotonic()
    try:
        workflows = await _create_onboarding_workflows(
            user_id,
            profession,
            has_gmail,
            focus,
            user_timezone,
            triage,
            writing_style,
            clarify_answers,
            selected_integrations,
        )
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} workflows failed",
            user_id=user_id,
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
        user_id=user_id,
        step="workflows",
        outcome="ok" if workflows else "empty",
        count=len(workflows),
        has_triage=triage is not None,
        has_writing_style=writing_style is not None,
        duration_s=round(time.monotonic() - t0, 2),
    )

    try:
        workflow_ids = [w["id"] for w in workflows if w.get("id")]
        if workflow_ids:
            await user_repository.set_suggested_workflows(user_id, workflow_ids)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} persist suggested_workflows failed",
            user_id=user_id,
            step="workflows",
            error=str(e)[:200],
            error_type=type(e).__name__,
        )

    n = len(workflows)
    await _emit_stage(
        user_id,
        OnboardingStage.WORKFLOWS_READY,
        {
            "workflows": workflows,
            "status_text": (
                f"Saved {n} workflow{'s' if n != 1 else ''}" if n > 0 else "No workflows to save"
            ),
        },
    )
    return workflows


async def _run_holo_card(
    user_id: str,
    user_doc: dict,
    focus: str,
    triage: InboxTriage | None,
    writing_style: WritingStyleProfile | None,
    social_profiles: list[SocialProfile] | None = None,
    clarify_answers: list[dict] | None = None,
) -> None:
    t0 = time.monotonic()
    try:
        context_parts: list[str] = []
        if triage:
            context_parts.append(f"Inbox summary: {triage.summary}")
            if triage.patterns:
                context_parts.append(f"Inbox patterns: {'; '.join(triage.patterns)}")
            if triage.important_emails:
                senders = ", ".join(e.sender for e in triage.important_emails[:5])
                context_parts.append(f"Key contacts: {senders}")
        if writing_style:
            context_parts.append(f"Writing style: {writing_style.summary}")
        if social_profiles:
            platforms = ", ".join(f"{p.platform}: {p.url}" for p in social_profiles)
            context_parts.append(f"Social profiles: {platforms}")
        if focus:
            context_parts.append(f"Current focus: {focus}")
        for answer in clarify_answers or []:
            value = (answer.get("value") or "").strip()
            if not value:
                continue
            kind = (answer.get("kind") or "context").strip() or "context"
            context_parts.append(f"{kind.capitalize()}: {value}")
        context_summary = "\n".join(context_parts)

        t_meta = time.monotonic()
        metadata = await get_user_metadata(user_id, user=user_doc)
        meta_duration_s = round(time.monotonic() - t_meta, 2)
        card_design = generate_profile_card_design()
        t_phrase_bio = time.monotonic()
        phrase, user_bio, bio_status = await generate_holo_card_content(
            user_id, context_summary, user=user_doc
        )
        phrase_bio_duration_s = round(time.monotonic() - t_phrase_bio, 2)
        t_save = time.monotonic()
        await save_personalization_data(
            user_id,
            card_design["house"],
            phrase,
            user_bio,
            bio_status,
            [],
            metadata["account_number"],
            metadata["member_since"],
            card_design["overlay_color"],
            card_design["overlay_opacity"],
        )
        log.info(
            f"{LogTag.ONBOARDING} holo_card done",
            user_id=user_id,
            step="holo_card",
            outcome="ok",
            house=card_design["house"],
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
            user_id=user_id,
            step="holo_card",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )

    await _emit_stage(user_id, OnboardingStage.HOLO_READY, {})


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
        await user_repository.set_social_profiles_if_unset(
            user_id, [p.model_dump() for p in social_profiles]
        )
    except Exception as e:
        log.error(f"{LogTag.ONBOARDING} persist social_profiles failed: {e}", exc_info=True)


async def _persist_profiles(
    user_id: str,
    writing_style: WritingStyleProfile | None,
    triage: InboxTriage | None,
) -> None:
    """Persist writing style and triage summary. Social profiles are persisted
    separately by the background task in _run_social_profiles_background."""
    t0 = time.monotonic()
    triage_summary = None
    if triage:
        triage_summary = {
            "total_scanned": triage.total_scanned,
            "total_unread": triage.total_unread,
            "summary": triage.summary,
            "patterns": triage.patterns,
            "important_emails": [
                {
                    "sender": e.sender,
                    "subject": e.subject,
                    "why_important": e.why_important,
                }
                for e in triage.important_emails[:5]
            ],
        }

    if writing_style or triage:
        try:
            await user_repository.set_writing_style_and_triage(
                user_id,
                writing_style_summary=writing_style.summary if writing_style else None,
                writing_style_example=(
                    writing_style.example.model_dump() if writing_style else None
                ),
                triage_summary=triage_summary,
            )
        except Exception as e:
            log.error(f"{LogTag.ONBOARDING} persist update_fields failed: {e}", exc_info=True)

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
        log.error(f"{LogTag.ONBOARDING} triage reconstruction failed: {e}", exc_info=True)
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
        log.error(f"{LogTag.ONBOARDING} writing_style reconstruction failed: {e}", exc_info=True)
        return None


async def _fetch_onboarding_todos(user_id: str) -> list[dict]:
    todos = await todo_repository.list_onboarding_todos(user_id, limit=ONBOARDING_TODO_LIMIT)
    return [{"id": todo.id, "title": todo.title or ""} for todo in todos]


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
    clarify_answers: list[dict] = onboarding.get("clarify_answers") or []
    selected_integrations: list[str] = onboarding.get("selected_integrations") or []
    user_timezone: str = (user.timezone or "UTC").strip() or "UTC"

    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(["gmail"], user_id)
    has_gmail: bool = connection_status.get("gmail", False)

    triage = _triage_from_doc(onboarding.get("triage_summary"))
    writing_style = _writing_style_from_doc(onboarding.get("writing_style"))

    # Idempotency: if a prior run of this phase was killed after creating some
    # workflows (leaving phase=PENDING so the stuck cron re-enqueues it), drop
    # those stale suggestions before regenerating so the retry replaces them
    # instead of doubling up. Onboarding workflows are created deactivated —
    # no Composio triggers or scheduled jobs to unwind — so a direct delete is safe.
    prior_workflow_ids = onboarding.get("suggested_workflows") or []
    if prior_workflow_ids:
        deleted = await workflow_repository.delete_many_for_user(prior_workflow_ids, user_id)
        log.info(
            f"{LogTag.ONBOARDING} workflows phase retry — purged {deleted} "
            f"stale suggested workflows before regenerating",
            user_id=user_id,
        )

    workflows = await _run_workflows(
        user_id,
        profession,
        has_gmail,
        focus,
        user_timezone,
        triage,
        writing_style,
        clarify_answers,
        selected_integrations,
    )

    todos = await _fetch_onboarding_todos(user_id)
    conversation_id = await _finalize_onboarding(
        user_id,
        name=name,
        profession=profession,
        triage=triage,
        todos=todos,
        workflows=workflows,
        writing_style=writing_style,
        has_gmail=has_gmail,
        focus=focus,
        clarify_answers=clarify_answers,
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
    clarify_answers: list[dict] | None = None,
) -> list[dict]:
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
            _FocusTodoList, prompt, label="onboarding_focus_todos"
        )
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        async def _create_one(title: str) -> dict | None:
            try:
                safe_title = title[:80].rsplit(" ", 1)[0] if len(title) > 80 else title
                todo = TodoModel(
                    title=safe_title,
                    description=f"Created from your focus: {focus[:200]}",
                    labels=["onboarding"],
                    priority=Priority.MEDIUM,
                    project_id=None,
                )
                result = await TodoService.create_todo(todo, user_id)
                return {"id": str(result.id), "title": safe_title}
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
) -> list[dict]:
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
            _TodoListFromEmails, prompt, label="onboarding_todos_from_emails"
        )
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        async def _create_one(spec: _TodoSpec) -> dict | None:
            try:
                safe_title = (
                    spec.title[:80].rsplit(" ", 1)[0] if len(spec.title) > 80 else spec.title
                )
                todo = TodoModel(
                    title=safe_title,
                    description=spec.description[:500],
                    labels=["onboarding"],
                    priority=Priority.MEDIUM,
                    project_id=None,
                )
                result = await TodoService.create_todo(todo, user_id)
                todo_dict: dict = {"id": str(result.id), "title": safe_title}
                sender_ok = spec.source_sender and spec.source_sender in real_senders
                subject_ok = spec.source_subject and spec.source_subject in real_subjects
                if sender_ok and subject_ok:
                    todo_dict["source_email"] = {
                        "sender": spec.source_sender,
                        "subject": spec.source_subject,
                    }
                elif spec.source_sender or spec.source_subject:
                    log.warning(
                        f"{LogTag.ONBOARDING} Dropped hallucinated source_email "
                        f"sender={spec.source_sender!r} subject={spec.source_subject!r}"
                    )
                return todo_dict
            except Exception as e:
                log.warning(f"{LogTag.ONBOARDING} Failed to create todo: {e}")
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
    suggestion: dict | None,
) -> TriggerConfig:
    """Map a SuggestedTrigger-like dict into a real TriggerConfig."""
    if not suggestion:
        return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")

    s_type = (suggestion.get("type") or "").lower()
    if s_type == "manual":
        return TriggerConfig(type=TriggerType.MANUAL)

    if s_type == "schedule":
        cron = (suggestion.get("cron_expression") or "0 9 * * *").strip()
        return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=cron)

    if s_type == "integration":
        slug = suggestion.get("trigger_name")
        schema = _find_workflow_trigger_schema(slug) if slug else None
        if not schema:
            return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")

        # Triggers with config fields need typed trigger_data we can't build
        # generically — fall back to a schedule for those.
        if schema.config_schema:
            return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")

        return TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name=slug,
        )

    return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")


def _find_workflow_trigger_schema(slug: str):
    for integration in OAUTH_INTEGRATIONS:
        for tc in integration.associated_triggers or []:
            if tc.workflow_trigger_schema and tc.workflow_trigger_schema.slug == slug:
                return tc.workflow_trigger_schema
    return None


def _serialize_trigger_for_payload(trigger_config: TriggerConfig) -> dict:
    payload: dict = {"type": str(trigger_config.type)}
    if trigger_config.cron_expression:
        payload["cron_expression"] = trigger_config.cron_expression
    if trigger_config.timezone:
        payload["timezone"] = trigger_config.timezone
    if trigger_config.trigger_name:
        payload["trigger_name"] = trigger_config.trigger_name
    return payload


def _build_workflow_prompt_context(
    profession: str,
    focus: str,
    has_gmail: bool,
    triage: InboxTriage | None,
    writing_style: WritingStyleProfile | None,
    clarify_answers: list[dict] | None,
    selected_integrations: list[str] | None = None,
) -> str:
    """Render the workflow-creation prompt from the user's onboarding context."""
    inbox_patterns = (
        "; ".join(triage.patterns[:3]) if triage and triage.patterns else "no patterns detected"
    )
    email_senders_summary = (
        ", ".join(e.sender for e in triage.important_emails[:5])
        if triage and triage.important_emails
        else "no email data"
    )
    writing_style_summary = writing_style.summary[:150] if writing_style else "not analyzed"

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
        profession=profession or "professional",
        focus=focus or NOT_SPECIFIED,
        clarify_context=format_clarify_context(clarify_answers),
        selected_integrations_section=selected_integrations_section,
        has_gmail=has_gmail,
        inbox_patterns=inbox_patterns,
        email_senders_summary=email_senders_summary,
        writing_style_summary=writing_style_summary,
    )


# Retries for the workflow-spec generation LLM call before giving up.
_WORKFLOW_SPEC_MAX_ATTEMPTS = 3


async def _generate_workflow_specs(user_id: str, prompt: str) -> _WorkflowList:
    """Invoke the LLM up to ``_WORKFLOW_SPEC_MAX_ATTEMPTS`` times until it returns
    exactly 4 workflow specs. Raises if no valid result is produced after the retries."""
    last_error: Exception | None = None
    for attempt in range(_WORKFLOW_SPEC_MAX_ATTEMPTS):
        try:
            candidate: _WorkflowList = await ainvoke_structured(
                _WorkflowList, prompt, label="onboarding_workflow_suggestions"
            )
            if len(candidate.workflows) == 4:
                return candidate
            log.warning(
                f"{LogTag.ONBOARDING} workflow specs wrong count, retrying",
                user_id=user_id,
                step="workflows_specs_llm",
                attempt=attempt,
                specs_count=len(candidate.workflows),
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

    if last_error is not None:
        raise last_error
    raise RuntimeError(
        f"LLM did not return exactly 4 workflow specs after {_WORKFLOW_SPEC_MAX_ATTEMPTS} attempts"
    )


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
) -> dict | None:
    """Generate the prompt + trigger for a single spec and persist the workflow."""
    t_spec = time.monotonic()
    try:
        t_prompt = time.monotonic()
        gen_result = await WorkflowGenerationService.generate_workflow_prompt(
            title=spec.title,
            description=spec.description,
        )
        prompt_duration_s = round(time.monotonic() - t_prompt, 2)
        workflow_prompt = (gen_result.get("prompt") or spec.description).strip()
        suggested = gen_result.get("suggested_trigger")
        suggested_dict = suggested.model_dump() if suggested is not None else None
        trigger_config = _build_trigger_config_from_suggestion(suggested_dict)

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
            trigger_type=str(trigger_config.type),
            workflow_id=str(workflow.id),
            prompt_duration_s=prompt_duration_s,
            create_duration_s=create_duration_s,
            duration_s=round(time.monotonic() - t_spec, 2),
        )
        # Surface step + trigger integrations the user hasn't connected so the
        # onboarding cards show the same missing-integration warning as the app.
        required = compute_required_integrations(workflow.steps, workflow.trigger_config)
        missing = await compute_missing_integrations(required, user_id)
        return {
            "id": str(workflow.id),
            "title": spec.title,
            "description": spec.description,
            "categories": spec.categories,
            "trigger": _serialize_trigger_for_payload(workflow.trigger_config),
            "missing_integrations": [{"id": ref.id, "name": ref.name} for ref in missing],
        }
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
    user_id: str,
    profession: str,
    has_gmail: bool,
    focus: str = "",
    user_timezone: str = "UTC",
    triage: InboxTriage | None = None,
    writing_style: WritingStyleProfile | None = None,
    clarify_answers: list[dict] | None = None,
    selected_integrations: list[str] | None = None,
) -> list[dict]:
    """Create 4 LLM-generated workflows tailored to the user's context."""
    # Keep only known integration ids (request-backed input), de-duped and
    # order-preserving. Include Gmail when connected and not already listed.
    effective_integrations: list[str] = [
        s for s in dict.fromkeys(selected_integrations or []) if s in OAUTH_INTEGRATION_NAME_BY_ID
    ]
    if has_gmail and "gmail" not in effective_integrations:
        effective_integrations.append("gmail")

    prompt = _build_workflow_prompt_context(
        profession,
        focus,
        has_gmail,
        triage,
        writing_style,
        clarify_answers,
        effective_integrations or None,
    )

    t0 = time.monotonic()
    try:
        t_specs_llm = time.monotonic()
        parsed = await _generate_workflow_specs(user_id, prompt)
        specs_llm_duration_s = round(time.monotonic() - t_specs_llm, 2)
        log.info(
            f"{LogTag.ONBOARDING} workflow specs generated",
            user_id=user_id,
            step="workflows_specs_llm",
            specs_count=len(parsed.workflows),
            llm_duration_s=specs_llm_duration_s,
        )
        specs_total = len(parsed.workflows)

        results = await asyncio.gather(
            *[
                _build_one_workflow(
                    user_id, idx, spec, user_timezone, effective_integrations or None
                )
                for idx, spec in enumerate(parsed.workflows)
            ]
        )
        created: list[dict] = [r for r in results if r is not None]
        specs_failed = specs_total - len(created)
        log.info(
            f"{LogTag.ONBOARDING} workflows specs done",
            user_id=user_id,
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
            user_id=user_id,
            step="workflows",
            error=str(e)[:200],
            error_type=type(e).__name__,
            fallback_used=True,
        )
        return await _create_fallback_workflow(
            user_id, focus, user_timezone, effective_integrations or None
        )


async def _create_fallback_workflow(
    user_id: str,
    focus: str = "",
    user_timezone: str = "UTC",
    integration_ids: list[str] | None = None,
) -> list[dict]:
    title = "Daily Briefing"
    description = (
        f"Every morning, summarize unread emails by priority, today's meetings, and open todos. "
        f"Focus: {focus[:100]}."
        if focus
        else "Every morning at 9am, summarize unread emails by priority, today's meetings, and open todos."
    )
    try:
        trigger_config = TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")
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
            {
                "id": str(workflow.id),
                "title": title,
                "description": description,
                "categories": [],
                "trigger": _serialize_trigger_for_payload(workflow.trigger_config),
            }
        ]
    except Exception as e:
        log.warning(f"{LogTag.ONBOARDING} Fallback workflow creation failed: {e}")
        return []
