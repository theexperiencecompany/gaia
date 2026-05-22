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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Optional, TypeVar

from bson import ObjectId
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from shared.py.wide_events import log

from app.agents.memory.email_processor import fetch_emails_for_onboarding
from app.agents.prompts.onboarding_prompts import (
    FOCUS_TODOS_PROMPT,
    TRIAGE_TODOS_PROMPT,
    WORKFLOW_CREATION_PROMPT,
)
from app.constants.email import ONBOARDING_EMAIL_SCAN_LIMIT
from app.constants.todos import ONBOARDING_TODO_LIMIT
from app.core.lazy_loader import providers
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import users_collection
from app.models.onboarding_models import (
    InboxTriage,
    SocialProfile,
    WritingStyleProfile,
)
from app.models.todo_models import Priority, TodoModel
from app.models.user_models import OnboardingPhase
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.workflow_models import CreateWorkflowRequest, TriggerConfig, TriggerType
from app.services.composio.composio_service import get_composio_service
from app.services.workflow.generation_service import WorkflowGenerationService
from app.utils.redis_utils import RedisPoolManager
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
from app.services.workflow.service import WorkflowService
from app.utils.profile_card import (
    generate_holo_card_content,
    generate_profile_card_design,
    get_user_metadata,
)
from app.utils.seeding_utils import seed_onboarding_conversation


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
    payload: Optional[dict] = None,
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
            log.info(f"[intelligence:stage] {stage.value} — {status_text}")
        else:
            log.info(f"[intelligence:stage] {stage.value}")
    except Exception as e:
        log.warning(f"[intelligence] Failed to emit stage {stage.value}: {e}")


T = TypeVar("T")


async def _safe_run(name: str, coro: Awaitable[T], default: T) -> T:
    try:
        return await coro
    except Exception as e:
        log.error(f"[intelligence] Node '{name}' failed: {e}", exc_info=True)
        return default


# Module-level set prevents GC of fire-and-forget tasks
_background_tasks: set[asyncio.Task] = set()


_TRIAGE_EARLY_THRESHOLD = 100

_NOT_SPECIFIED = "not specified"


@dataclass
class InboxScanContext:
    """Shared state between the inbox fetch task and triage (which starts
    as soon as enough emails are buffered)."""

    emails: list[dict] = field(default_factory=list)
    first_batch_ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


class _TodoSpec(BaseModel):
    title: str = Field(
        description="What GAIA will do — under 80 chars, starts with a verb"
    )
    description: str = Field(
        description="Context and what the output will be — 1-2 sentences"
    )
    source_sender: str = Field(
        default="",
        description="The sender of the email this todo was created from. Empty string if not from a specific email.",
    )
    source_subject: str = Field(
        default="",
        description="The subject line of the email this todo was created from. Empty string if not from a specific email.",
    )


class _TodoListFromEmails(BaseModel):
    todos: list[_TodoSpec] = Field(
        description="List of exactly 3 GAIA-actionable todo items"
    )


class _FocusTodoList(BaseModel):
    todos: list[str] = Field(
        description="List of 3 GAIA-actionable todo titles — each under 60 characters, starts with a verb"
    )


class _WorkflowSpec(BaseModel):
    title: str = Field(
        description="Workflow title — under 60 chars, starts with a verb or noun"
    )
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


async def _scan_then_enqueue_mem0(user_id: str, ctx: InboxScanContext) -> None:
    """Run the visible inbox scan, then queue durable Mem0 ingestion so it
    runs in parallel with triage/workflows and survives later failures."""
    await _run_inbox_scanning(user_id, ctx)
    try:
        pool = await RedisPoolManager.get_pool()
        await pool.enqueue_job("process_gmail_emails_to_memory", user_id)
        log.info(
            "[intelligence] queued gmail->mem0 ingestion",
            user_id=user_id,
        )
    except Exception as e:
        log.warning(
            "[intelligence] failed to queue gmail->mem0 ingestion",
            user_id=user_id,
            error=str(e)[:200],
            error_type=type(e).__name__,
        )


def _start_gmail_branch(
    user_id: str,
) -> tuple[InboxScanContext, asyncio.Task[None]]:
    """Kick off the Gmail-only inbox scan + Mem0 ingestion task and the system
    workflow provisioning task. Returns the shared inbox context and the
    provision future."""
    inbox_ctx = InboxScanContext()
    scan_task = asyncio.create_task(_scan_then_enqueue_mem0(user_id, inbox_ctx))
    _background_tasks.add(scan_task)
    scan_task.add_done_callback(_background_tasks.discard)
    provision_future = asyncio.create_task(_run_provision_gmail(user_id))
    return inbox_ctx, provision_future


async def _persist_completion(
    user_id: str,
    conversation_id: Optional[str],
    provision_future: Optional[asyncio.Task[None]],
) -> None:
    """Write the unconditional end-of-pipeline phase transition and keep any
    still-running provision task alive past pipeline return."""
    completion_update: dict[str, object] = {
        "onboarding.phase": OnboardingPhase.PERSONALIZATION_COMPLETE,
        "updated_at": datetime.now(timezone.utc),
    }
    if conversation_id:
        completion_update["onboarding.first_message_conversation_id"] = conversation_id
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": completion_update},
    )

    if provision_future is not None and not provision_future.done():
        _background_tasks.add(provision_future)
        provision_future.add_done_callback(_background_tasks.discard)


async def _social_then_holo(
    user_id: str,
    name: str,
    user_email: Optional[str],
    user_doc: dict,
    focus: str,
    triage: Optional[InboxTriage],
    writing_style: Optional[WritingStyleProfile],
    clarify_answers: list[dict],
    has_gmail: bool,
) -> None:
    """Extract social profiles (Gmail-only) then build the holo card."""
    social_profiles: list[SocialProfile] = []
    if has_gmail:
        social_profiles = await _run_social_profiles_background(
            user_id, name, user_email
        )
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
        "[intelligence] pipeline start",
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

    user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        log.error(
            "[intelligence] user not found",
            user_id=user_id,
            outcome="aborted",
            reason="user_not_found",
        )
        return

    onboarding = user_doc.get("onboarding", {})
    name: str = user_doc.get("name", "there")
    user_email: Optional[str] = user_doc.get("email")
    profession: str = onboarding.get("preferences", {}).get("profession", "") or ""
    focus: str = onboarding.get("focus", "") or ""
    clarify_answers: list[dict] = onboarding.get("clarify_answers") or []

    t_gmail_check = time.monotonic()
    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(
        ["gmail"], user_id
    )
    has_gmail: bool = connection_status.get("gmail", False)
    log.info(
        "[intelligence] gmail check",
        user_id=user_id,
        has_gmail=has_gmail,
        duration_s=round(time.monotonic() - t_gmail_check, 2),
    )
    log.info(
        "[intelligence] inputs",
        user_id=user_id,
        has_gmail=has_gmail,
        profession_set=bool(profession),
        focus_set=bool(focus),
        branch="gmail" if has_gmail else "no_gmail",
    )

    inbox_ctx: Optional[InboxScanContext] = None
    provision_future: Optional[asyncio.Task[None]] = None

    if has_gmail:
        inbox_ctx, provision_future = _start_gmail_branch(user_id)

    writing_style_future: asyncio.Task[Optional[WritingStyleProfile]] = (
        asyncio.create_task(_run_writing_style(user_id, has_gmail, profession))
    )

    triage_future = asyncio.create_task(
        _run_triage(user_id, inbox_ctx, profession, focus)
    )
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
    workflows_future = asyncio.create_task(
        _run_workflows(
            user_id,
            profession,
            has_gmail,
            focus,
            user_timezone,
            triage_future,
            writing_style_future,
            clarify_answers,
        )
    )
    t_gather = time.monotonic()
    triage, todos, workflows, writing_style = await asyncio.gather(
        triage_future,
        todos_future,
        workflows_future,
        writing_style_future,
    )
    log.info(
        "[intelligence] critical_path gathered",
        user_id=user_id,
        phase="critical_path_gather",
        duration_s=round(time.monotonic() - t_gather, 2),
    )

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
        default="Welcome to GAIA. I'm here to help — what's on your mind?",
    )
    log.info(
        "[intelligence] first_message generated",
        user_id=user_id,
        message_chars=len(first_message),
        duration_s=round(time.monotonic() - t_msg, 2),
    )

    # Persist first_message before the holo gather: holo_ready triggers a
    # frontend fetch of /onboarding/personalization, which must not see null.
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.first_message": first_message}},
    )

    t_final = time.monotonic()
    conversation_id, _, _ = await asyncio.gather(
        _seed_conversation(user_id),
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
    log.info(
        "[intelligence] finalize gathered",
        user_id=user_id,
        phase="finalize_gather",
        duration_s=round(time.monotonic() - t_final, 2),
    )

    # Unconditional end-of-pipeline phase transition: guarantees the user
    # advances even if the holo leg (which also writes this) failed.
    await _persist_completion(user_id, conversation_id, provision_future)

    await _emit_stage(
        user_id,
        OnboardingStage.COMPLETE,
        {"conversation_id": conversation_id},
    )

    log.info(
        "[intelligence] pipeline done",
        user_id=user_id,
        phase="done",
        has_gmail=has_gmail,
        writing_style_learned=writing_style is not None,
        triage_important_count=len(triage.important_emails) if triage else 0,
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
            "[intelligence] inbox_scanning cache_hit",
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
        if not ctx.first_batch_ready.is_set() and current >= _TRIAGE_EARLY_THRESHOLD:
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
            "[intelligence] inbox_scanning failed",
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
        "[intelligence] inbox_scanning done",
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
            "[intelligence] provision_gmail done",
            user_id=user_id,
            step="provision_gmail",
            outcome="ok",
            duration_s=round(time.monotonic() - t0, 2),
        )
    except Exception as e:
        log.warning(
            "[intelligence] provision_gmail failed",
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
) -> Optional[WritingStyleProfile]:
    """Learn writing style from the user's last 50 sent emails. Gmail-only."""
    if not has_gmail:
        log.info(
            "[intelligence] writing_style skipped",
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
        result = await learn_writing_style(
            user_id, profession=profession, on_status=_on_status
        )
    except Exception as e:
        log.error(
            "[intelligence] writing_style failed",
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
        "[intelligence] writing_style done",
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
            "example": result.example.model_dump()
            if result and result.example
            else None,
        },
    )
    return result


async def _run_triage(
    user_id: str,
    inbox_ctx: Optional[InboxScanContext],
    profession: str,
    focus: str,
) -> Optional[InboxTriage]:
    if inbox_ctx is None:
        log.info(
            "[intelligence] triage skipped",
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
            "[intelligence] triage skipped",
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
            "[intelligence] triage failed",
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
        "[intelligence] triage done",
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
    user_email: Optional[str],
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
            raw = await extract_social_profiles_from_emails(
                emails, user_name, user_email
            )
            raw_count = len(raw)
            profiles = dedup_profiles_by_platform(raw)
            await _persist_social_profiles(user_id, profiles)
            log.info(
                "[intelligence] social_profiles done",
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
            "[intelligence] social_profiles failed",
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
    triage_future: asyncio.Task[Optional[InboxTriage]],
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
                todos = await _create_focus_todos(
                    user_id, name, profession, focus, clarify_answers
                )
        elif focus:
            source = "focus"
            await _emit_stage(
                user_id,
                OnboardingStage.TODOS_CREATING,
                {"status_text": "Drafting todos from your focus"},
            )
            todos = await _create_focus_todos(
                user_id, name, profession, focus, clarify_answers
            )
    except Exception as e:
        log.error(
            "[intelligence] todos failed",
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
        "[intelligence] todos done",
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
                f"Saved {n} todo{'s' if n != 1 else ''}"
                if n > 0
                else "No todos to save"
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
    triage_future: asyncio.Task[Optional[InboxTriage]],
    writing_style_future: asyncio.Task[Optional[WritingStyleProfile]],
    clarify_answers: list[dict] | None = None,
) -> list[dict]:
    triage, writing_style = await asyncio.gather(triage_future, writing_style_future)

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
        )
    except Exception as e:
        log.error(
            "[intelligence] workflows failed",
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
        "[intelligence] workflows done",
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
            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"onboarding.suggested_workflows": workflow_ids}},
            )
    except Exception as e:
        log.warning(
            "[intelligence] persist suggested_workflows failed",
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
                f"Saved {n} workflow{'s' if n != 1 else ''}"
                if n > 0
                else "No workflows to save"
            ),
        },
    )
    return workflows


async def _run_holo_card(
    user_id: str,
    user_doc: dict,
    focus: str,
    triage: Optional[InboxTriage],
    writing_style: Optional[WritingStyleProfile],
    social_profiles: Optional[list[SocialProfile]] = None,
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
            "[intelligence] holo_card done",
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
            "[intelligence] holo_card failed",
            user_id=user_id,
            step="holo_card",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )

    await _emit_stage(user_id, OnboardingStage.HOLO_READY, {})


async def _seed_conversation(user_id: str) -> Optional[str]:
    t0 = time.monotonic()
    try:
        cid = await seed_onboarding_conversation(user_id=user_id)
    except Exception as e:
        log.error(
            "[intelligence] seed_conversation failed",
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
        "[intelligence] seed_conversation done",
        user_id=user_id,
        step="seed_conversation",
        outcome="ok",
        conversation_id=cid,
        duration_s=round(time.monotonic() - t0, 2),
    )
    return cid


async def _persist_social_profiles(
    user_id: str, social_profiles: list[SocialProfile]
) -> None:
    """Write auto-extracted profiles only if the user hasn't already confirmed
    them via POST /social-profiles."""
    if not social_profiles:
        return
    try:
        await users_collection.update_one(
            {
                "_id": ObjectId(user_id),
                "$or": [
                    {"onboarding.social_profiles": {"$exists": False}},
                    {"onboarding.social_profiles": None},
                    {"onboarding.social_profiles": []},
                ],
            },
            {
                "$set": {
                    "onboarding.social_profiles": [
                        p.model_dump() for p in social_profiles
                    ]
                }
            },
        )
    except Exception as e:
        log.error(f"[intelligence] persist social_profiles failed: {e}", exc_info=True)


async def _persist_profiles(
    user_id: str,
    writing_style: Optional[WritingStyleProfile],
    triage: Optional[InboxTriage],
) -> None:
    """Persist writing style and triage summary. Social profiles are persisted
    separately by the background task in _run_social_profiles_background."""
    t0 = time.monotonic()
    update_fields: dict = {}
    if writing_style:
        update_fields["onboarding.writing_style.summary"] = writing_style.summary
        update_fields["onboarding.writing_style.example"] = (
            writing_style.example.model_dump()
        )
    if triage:
        update_fields["onboarding.triage_summary"] = {
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

    if update_fields:
        try:
            await users_collection.update_one(
                {"_id": ObjectId(user_id)}, {"$set": update_fields}
            )
        except Exception as e:
            log.error(
                f"[intelligence] persist update_fields failed: {e}", exc_info=True
            )

    log.info(
        "[intelligence] persist_profiles done",
        user_id=user_id,
        step="persist_profiles",
        writing_style_persisted=writing_style is not None,
        triage_persisted=triage is not None,
        duration_s=round(time.monotonic() - t0, 2),
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
        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        structured_llm = llm.with_structured_output(_FocusTodoList)
        t_llm = time.monotonic()
        parsed: _FocusTodoList = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        async def _create_one(title: str) -> Optional[dict]:
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
                    "[intelligence] focus todo create failed",
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
            "[intelligence] focus_todos done",
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
            "[intelligence] focus_todos failed",
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
        profession=profession or _NOT_SPECIFIED,
        focus=focus or _NOT_SPECIFIED,
        format_instructions="Return a JSON object with a 'todos' key containing a list of todo objects, each with 'title', 'description', 'source_sender', and 'source_subject'.",
    )

    t0 = time.monotonic()
    try:
        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        structured_llm = llm.with_structured_output(_TodoListFromEmails)
        t_llm = time.monotonic()
        parsed: _TodoListFromEmails = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        async def _create_one(spec: _TodoSpec) -> Optional[dict]:
            try:
                safe_title = (
                    spec.title[:80].rsplit(" ", 1)[0]
                    if len(spec.title) > 80
                    else spec.title
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
                subject_ok = (
                    spec.source_subject and spec.source_subject in real_subjects
                )
                if sender_ok and subject_ok:
                    todo_dict["source_email"] = {
                        "sender": spec.source_sender,
                        "subject": spec.source_subject,
                    }
                elif spec.source_sender or spec.source_subject:
                    log.warning(
                        "[intelligence] Dropped hallucinated source_email "
                        f"sender={spec.source_sender!r} subject={spec.source_subject!r}"
                    )
                return todo_dict
            except Exception as e:
                log.warning(f"[intelligence] Failed to create todo: {e}")
                return None

        t_create = time.monotonic()
        results = await asyncio.gather(
            *[_create_one(s) for s in parsed.todos[:ONBOARDING_TODO_LIMIT]]
        )
        created = [r for r in results if r is not None]
        log.info(
            "[intelligence] triage_todos done",
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
            "[intelligence] triage_todos failed",
            user_id=user_id,
            step="todos_triage",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return []


def _build_trigger_config_from_suggestion(
    suggestion: Optional[dict],
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
    triage: Optional[InboxTriage],
    writing_style: Optional[WritingStyleProfile],
    clarify_answers: list[dict] | None,
) -> str:
    """Render the workflow-creation prompt from the user's onboarding context."""
    inbox_patterns = (
        "; ".join(triage.patterns[:3])
        if triage and triage.patterns
        else "no patterns detected"
    )
    email_senders_summary = (
        ", ".join(e.sender for e in triage.important_emails[:5])
        if triage and triage.important_emails
        else "no email data"
    )
    writing_style_summary = (
        writing_style.summary[:150] if writing_style else "not analyzed"
    )
    return WORKFLOW_CREATION_PROMPT.format(
        profession=profession or "professional",
        focus=focus or _NOT_SPECIFIED,
        clarify_context=format_clarify_context(clarify_answers),
        has_gmail=has_gmail,
        inbox_patterns=inbox_patterns,
        email_senders_summary=email_senders_summary,
        writing_style_summary=writing_style_summary,
    )


async def _generate_workflow_specs(user_id: str, prompt: str) -> _WorkflowList:
    """Invoke the LLM up to 3 times until it returns exactly 4 workflow specs.
    Raises if no valid result is produced after the retries."""
    llm = await providers.aget("gemini_llm")
    if llm is None:
        raise RuntimeError("LLM provider not available")
    structured_llm = llm.with_structured_output(_WorkflowList)

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            candidate: _WorkflowList = await structured_llm.ainvoke(
                [HumanMessage(content=prompt)]
            )
            if len(candidate.workflows) == 4:
                return candidate
            log.warning(
                "[intelligence] workflow specs wrong count, retrying",
                user_id=user_id,
                step="workflows_specs_llm",
                attempt=attempt,
                specs_count=len(candidate.workflows),
            )
        except Exception as e:
            last_error = e
            log.warning(
                "[intelligence] workflow specs llm failed, retrying",
                user_id=user_id,
                step="workflows_specs_llm",
                attempt=attempt,
                error=str(e)[:200],
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM did not return exactly 4 workflow specs after 3 attempts")


async def _build_one_workflow(
    user_id: str,
    idx: int,
    spec: _WorkflowSpec,
    user_timezone: str,
) -> Optional[dict]:
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
        )
        t_create = time.monotonic()
        workflow = await WorkflowService.create_workflow(
            request, user_id, user_timezone=user_timezone
        )
        create_duration_s = round(time.monotonic() - t_create, 2)
        log.info(
            "[intelligence] workflow spec done",
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
        return {
            "id": str(workflow.id),
            "title": spec.title,
            "description": spec.description,
            "categories": spec.categories,
            "trigger": _serialize_trigger_for_payload(workflow.trigger_config),
        }
    except Exception as e:
        log.warning(
            "[intelligence] workflow spec failed",
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
    triage: Optional[InboxTriage] = None,
    writing_style: Optional[WritingStyleProfile] = None,
    clarify_answers: list[dict] | None = None,
) -> list[dict]:
    """Create 4 LLM-generated workflows tailored to the user's context."""
    prompt = _build_workflow_prompt_context(
        profession,
        focus,
        has_gmail,
        triage,
        writing_style,
        clarify_answers,
    )

    t0 = time.monotonic()
    try:
        t_specs_llm = time.monotonic()
        parsed = await _generate_workflow_specs(user_id, prompt)
        specs_llm_duration_s = round(time.monotonic() - t_specs_llm, 2)
        log.info(
            "[intelligence] workflow specs generated",
            user_id=user_id,
            step="workflows_specs_llm",
            specs_count=len(parsed.workflows),
            llm_duration_s=specs_llm_duration_s,
        )
        specs_total = len(parsed.workflows)

        results = await asyncio.gather(
            *[
                _build_one_workflow(user_id, idx, spec, user_timezone)
                for idx, spec in enumerate(parsed.workflows)
            ]
        )
        created: list[dict] = [r for r in results if r is not None]
        specs_failed = specs_total - len(created)
        log.info(
            "[intelligence] workflows specs done",
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
            "[intelligence] workflow LLM failed, using fallback",
            user_id=user_id,
            step="workflows",
            error=str(e)[:200],
            error_type=type(e).__name__,
            fallback_used=True,
        )
        return await _create_fallback_workflow(user_id, focus, user_timezone)


async def _create_fallback_workflow(
    user_id: str,
    focus: str = "",
    user_timezone: str = "UTC",
) -> list[dict]:
    title = "Daily Briefing"
    description = (
        f"Every morning, summarize unread emails by priority, today's meetings, and open todos. "
        f"Focus: {focus[:100]}."
        if focus
        else "Every morning at 9am, summarize unread emails by priority, today's meetings, and open todos."
    )
    try:
        trigger_config = TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression="0 9 * * *"
        )
        request = CreateWorkflowRequest(
            title=title,
            description=description,
            prompt=description,
            trigger_config=trigger_config,
            generate_immediately=True,
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
        log.warning(f"[intelligence] Fallback workflow creation failed: {e}")
        return []
