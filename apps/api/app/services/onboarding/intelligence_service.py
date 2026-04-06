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

Holo card runs fully independently. Memory ingestion is fire-and-forget.
"""

import asyncio
import time
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
from app.core.lazy_loader import providers
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import users_collection
from app.helpers.email_helpers import (
    mark_email_processing_complete,
    process_email_content,
    store_emails_to_mem0,
)
from app.models.onboarding_models import (
    InboxTriage,
    SocialProfile,
    WritingStyleProfile,
)
from app.models.todo_models import Priority, TodoModel
from app.models.workflow_models import CreateWorkflowRequest, TriggerConfig, TriggerType
from app.services.composio.composio_service import get_composio_service
from app.services.onboarding.first_message_service import generate_first_message
from app.services.onboarding.inbox_triage_service import triage_inbox
from app.services.onboarding.post_onboarding_service import (
    save_personalization_data,
    suggest_workflows_via_rag,
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
    generate_personality_phrase,
    generate_profile_card_design,
    generate_user_bio,
    get_user_metadata,
)
from app.utils.seeding_utils import seed_onboarding_conversation


# ── Stage enum + emit helper ──────────────────────────────────────────────────


class OnboardingStage(str, Enum):
    """Stages emitted over WebSocket during onboarding intelligence.

    Every stage fires exactly once per pipeline run EXCEPT INBOX_SCANNING,
    which fires multiple times with {"current": n} payloads from the Gmail
    fetch's on_batch callback so the user sees a live "N emails fetched" counter.
    """

    INBOX_SCANNING = "inbox_scanning"  # repeats; carries {current: n}
    WRITING_STYLE_READY = "writing_style_ready"
    SOCIAL_PROFILES_READY = "social_profiles_ready"
    TRIAGE_ANALYZING = "triage_analyzing"  # LLM is processing inbox
    TRIAGE_ANALYZED = "triage_analyzed"  # found X important threads
    TRIAGE_READY = "triage_ready"
    TODOS_CREATING = "todos_creating"  # about to create todos
    TODOS_READY = "todos_ready"
    WORKFLOWS_READY = "workflows_ready"
    HOLO_READY = "holo_ready"
    COMPLETE = "complete"


async def _emit_stage(
    user_id: str,
    stage: OnboardingStage,
    payload: Optional[dict] = None,
) -> None:
    """Emit an onboarding_stage event to the user's WebSocket channel."""
    try:
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "onboarding_stage",
                "data": {"stage": stage.value, "payload": payload or {}},
            },
        )
        log.info(f"[intelligence:stage] {stage.value}")
    except Exception as e:
        log.warning(f"[intelligence] Failed to emit stage {stage.value}: {e}")


# ── Safe-run helper ──────────────────────────────────────────────────────────


T = TypeVar("T")


async def _safe_run(name: str, coro: Awaitable[T], default: T) -> T:
    """Run a coroutine, swallow any exception, log with traceback, return default."""
    try:
        return await coro
    except Exception as e:
        log.error(f"[intelligence] Node '{name}' failed: {e}", exc_info=True)
        return default


# Module-level set prevents GC of fire-and-forget tasks
_background_tasks: set[asyncio.Task] = set()


# ── Pydantic spec models for LLM structured outputs ──────────────────────────


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
    workflows: list[_WorkflowSpec] = Field(description="Exactly 2 workflow specs")


# ── Main orchestrator ────────────────────────────────────────────────────────


async def process_onboarding_intelligence(user_id: str) -> None:
    """Main onboarding intelligence DAG. Called as an ARQ background task
    after POST /onboarding.
    """
    log.set(user={"id": user_id})
    pipeline_start = time.monotonic()
    log.info(f"[intelligence] Starting onboarding intelligence for {user_id}")

    user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        log.error(f"[intelligence] User not found: {user_id}")
        return

    onboarding = user_doc.get("onboarding", {})
    name: str = user_doc.get("name", "there")
    user_email: Optional[str] = user_doc.get("email")
    profession: str = onboarding.get("preferences", {}).get("profession", "") or ""
    focus: str = onboarding.get("focus", "") or ""

    # Gmail availability
    t_gmail_check = time.monotonic()
    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(
        ["gmail"], user_id
    )
    has_gmail: bool = connection_status.get("gmail", False)
    log.info(
        f"[intelligence:timing] gmail_check: {time.monotonic() - t_gmail_check:.1f}s (has_gmail={has_gmail})"
    )

    # ── Roots (fire at t=0) ──────────────────────────────────────────────
    inbox_emails_future: Optional[asyncio.Task[list[dict]]] = None
    provision_future: Optional[asyncio.Task[None]] = None

    if has_gmail:
        inbox_emails_future = asyncio.create_task(_run_inbox_scanning(user_id))
        provision_future = asyncio.create_task(_run_provision_gmail(user_id))

    # Writing style is created unconditionally — returns None for no-Gmail users.
    # Owns its own 50-sent-email fetch internally (no shared future with inbox scan).
    writing_style_future: asyncio.Task[Optional[WritingStyleProfile]] = (
        asyncio.create_task(_run_writing_style(user_id, has_gmail, profession))
    )

    # ── Fire-and-forget memory ingestion ─────────────────────────────────
    # Kicked off as soon as inbox emails arrive; never awaited by the pipeline.
    # Hold a reference in _background_tasks so the outer task is not GC'd
    # before its inner _store task is created.
    memory_outer_task = asyncio.create_task(
        _fire_and_forget_memory_ingestion(
            user_id, name, user_email, inbox_emails_future
        )
    )
    _background_tasks.add(memory_outer_task)
    memory_outer_task.add_done_callback(_background_tasks.discard)

    # ── Derived nodes ────────────────────────────────────────────────────
    triage_future = asyncio.create_task(
        _run_triage(user_id, inbox_emails_future, profession, focus)
    )
    social_profiles_future = asyncio.create_task(
        _run_social_profiles(user_id, name, user_email, inbox_emails_future)
    )
    todos_future = asyncio.create_task(
        _run_todos(user_id, name, profession, focus, has_gmail, triage_future)
    )
    workflows_future = asyncio.create_task(
        _run_workflows(
            user_id,
            profession,
            has_gmail,
            focus,
            triage_future,
            writing_style_future,
        )
    )
    holo_future = asyncio.create_task(
        _run_holo_card(
            user_id,
            user_doc,
            profession,
            focus,
            triage_future,
            writing_style_future,
            social_profiles_future,
        )
    )

    # ── First message — does NOT wait for holo card ──────────────────────
    triage, todos, workflows, writing_style, social_profiles = await asyncio.gather(
        triage_future,
        todos_future,
        workflows_future,
        writing_style_future,
        social_profiles_future,
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
            social_profiles=[p.model_dump() for p in social_profiles],
            writing_style=writing_style,
            focus=focus,
        ),
        default="Welcome to GAIA. I'm here to help — what's on your mind?",
    )
    log.info(
        f"[intelligence:timing] generate_first_message: {time.monotonic() - t_msg:.1f}s"
    )

    # ── Seed conversation, persist, and wait for holo in parallel ────────
    conversation_id, _, _ = await asyncio.gather(
        _seed_conversation(user_id, first_message),
        _persist_profiles(user_id, writing_style, triage, social_profiles),
        holo_future,
    )

    if conversation_id:
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"onboarding.first_message_conversation_id": conversation_id}},
        )

    # Don't block completion on Gmail workflow provisioning — it's already
    # running; let it finish whenever.
    if provision_future is not None and not provision_future.done():
        _background_tasks.add(provision_future)
        provision_future.add_done_callback(_background_tasks.discard)

    await _emit_stage(
        user_id,
        OnboardingStage.COMPLETE,
        {"conversation_id": conversation_id},
    )

    log.info(
        f"[intelligence:timing] Pipeline total: {time.monotonic() - pipeline_start:.1f}s"
    )


# ── Root wrappers ────────────────────────────────────────────────────────────


async def _run_inbox_scanning(user_id: str) -> list[dict]:
    """Fetch the inbox for triage + social profile extraction.
    Emits INBOX_SCANNING repeatedly with {"current": n} as batches land."""
    t0 = time.monotonic()

    async def _on_batch(current: int) -> None:
        await _emit_stage(
            user_id,
            OnboardingStage.INBOX_SCANNING,
            {"current": current},
        )

    try:
        emails = await fetch_emails_for_onboarding(
            user_id,
            months=1,
            max_total=ONBOARDING_EMAIL_SCAN_LIMIT,
            on_batch=_on_batch,
        )
    except Exception as e:
        log.error(f"[intelligence] inbox_scanning failed: {e}", exc_info=True)
        return []

    log.info(
        f"[intelligence:timing] inbox_scanning: {time.monotonic() - t0:.1f}s ({len(emails)} emails)"
    )
    return emails


async def _run_provision_gmail(user_id: str) -> None:
    """Fire Gmail system workflow provisioning as a root. No deps."""
    try:
        await provision_system_workflows(user_id, "gmail", "Gmail")
    except Exception as e:
        log.warning(f"[intelligence] Gmail provisioning failed: {e}")


async def _run_writing_style(
    user_id: str,
    has_gmail: bool,
    profession: str,
) -> Optional[WritingStyleProfile]:
    """Learn writing style from the user's last 50 sent emails.

    Emits WRITING_STYLE_READY even when no style could be learned (no Gmail,
    zero sent emails, or LLM failure) so the frontend can show a graceful
    fallback card instead of a stuck spinner.
    """
    if not has_gmail:
        await _emit_stage(
            user_id,
            OnboardingStage.WRITING_STYLE_READY,
            {"style_summary": None, "example": None},
        )
        return None

    t0 = time.monotonic()
    try:
        result = await learn_writing_style(user_id, profession=profession)
    except Exception as e:
        log.error(f"[intelligence] writing_style failed: {e}", exc_info=True)
        result = None

    log.info(f"[intelligence:timing] writing_style: {time.monotonic() - t0:.1f}s")

    if result and result.summary and result.example:
        await _emit_stage(
            user_id,
            OnboardingStage.WRITING_STYLE_READY,
            {"style_summary": result.summary, "example": result.example},
        )
    else:
        await _emit_stage(
            user_id,
            OnboardingStage.WRITING_STYLE_READY,
            {"style_summary": None, "example": None},
        )
    return result


# ── Fire-and-forget memory ingestion ─────────────────────────────────────────


async def _fire_and_forget_memory_ingestion(
    user_id: str,
    user_name: str,
    user_email: Optional[str],
    inbox_emails_future: Optional[asyncio.Task[list[dict]]],
) -> None:
    """Wait for the shared inbox fetch, then store those emails to Mem0 in a
    task that is NEVER awaited by the pipeline. Uses the same emails already
    fetched by _run_inbox_scanning — no second Gmail fetch."""
    if inbox_emails_future is None:
        return
    try:
        emails = await inbox_emails_future
    except Exception:
        return
    if not emails:
        return

    async def _store() -> None:
        try:
            # Check if already processed (idempotency for ARQ retries)
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user and user.get("email_memory_processed", False):
                log.info(
                    f"[intelligence] User {user_id} memory already processed, skipping"
                )
                return

            t0 = time.monotonic()
            processed, failed = process_email_content(emails)
            if not processed:
                log.info(
                    f"[intelligence] No processable emails for memory ({failed} failed)"
                )
                return
            await store_emails_to_mem0(
                user_id, processed, user_name, user_email, async_mode=True
            )
            await mark_email_processing_complete(user_id, len(processed))
            log.info(
                f"[intelligence:timing] memory_ingestion (fire-and-forget): "
                f"{time.monotonic() - t0:.1f}s ({len(processed)} emails)"
            )
        except Exception as e:
            log.warning(f"[intelligence] Memory ingestion failed: {e}")

    task = asyncio.create_task(_store())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ── Derived node wrappers ────────────────────────────────────────────────────


async def _run_triage(
    user_id: str,
    inbox_emails_future: Optional[asyncio.Task[list[dict]]],
    profession: str,
    focus: str,
) -> Optional[InboxTriage]:
    if inbox_emails_future is None:
        # Always emit so the frontend can skip the triage reveal card
        await _emit_stage(
            user_id,
            OnboardingStage.TRIAGE_READY,
            {
                "total_scanned": 0,
                "total_unread": 0,
                "summary": None,
                "patterns": [],
                "important_emails": [],
            },
        )
        return None
    emails = await inbox_emails_future
    if not emails:
        await _emit_stage(
            user_id,
            OnboardingStage.TRIAGE_READY,
            {
                "total_scanned": 0,
                "total_unread": 0,
                "summary": None,
                "patterns": [],
                "important_emails": [],
            },
        )
        return None

    await _emit_stage(
        user_id,
        OnboardingStage.TRIAGE_ANALYZING,
        {"total_emails": len(emails), "status": "Analyzing your inbox..."},
    )

    t0 = time.monotonic()
    try:
        result = await triage_inbox(user_id, emails, profession=profession, focus=focus)
    except Exception as e:
        log.error(f"[intelligence] triage failed: {e}", exc_info=True)
        result = None
    log.info(f"[intelligence:timing] triage: {time.monotonic() - t0:.1f}s")

    if result and result.important_emails:
        await _emit_stage(
            user_id,
            OnboardingStage.TRIAGE_ANALYZED,
            {
                "important_count": len(result.important_emails),
                "status": f"Found {len(result.important_emails)} important thread(s)",
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


async def _run_social_profiles(
    user_id: str,
    user_name: str,
    user_email: Optional[str],
    inbox_emails_future: Optional[asyncio.Task[list[dict]]],
) -> list[SocialProfile]:
    if inbox_emails_future is None:
        return []
    emails = await inbox_emails_future
    if not emails:
        return []

    t0 = time.monotonic()
    try:
        profiles = await extract_social_profiles_from_emails(
            emails, user_name, user_email
        )
    except Exception as e:
        log.error(f"[intelligence] social_profiles failed: {e}", exc_info=True)
        profiles = []

    # Safety net — ensure one profile per platform
    profiles = dedup_profiles_by_platform(profiles)

    log.info(
        f"[intelligence:timing] social_profiles: {time.monotonic() - t0:.1f}s "
        f"({len(profiles)} profiles)"
    )
    # Always emit so the frontend has a definitive signal the stage finished,
    # even if no profiles were found.
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
) -> list[dict]:
    t0 = time.monotonic()
    todos: list[dict] = []
    try:
        if has_gmail:
            triage = await triage_future
            await _emit_stage(
                user_id,
                OnboardingStage.TODOS_CREATING,
                {"status": "Creating action items..."},
            )
            if triage and triage.important_emails:
                todos = await _create_todos_from_triage(
                    user_id, triage, profession=profession, focus=focus
                )
            elif focus:
                todos = await _create_focus_todos(user_id, name, profession, focus)
        elif focus:
            await _emit_stage(
                user_id,
                OnboardingStage.TODOS_CREATING,
                {"status": "Creating action items..."},
            )
            todos = await _create_focus_todos(user_id, name, profession, focus)
    except Exception as e:
        log.error(f"[intelligence] todos failed: {e}", exc_info=True)
        todos = []

    log.info(
        f"[intelligence:timing] todos: {time.monotonic() - t0:.1f}s ({len(todos)} todos)"
    )
    # Always emit so the frontend has a definitive completion signal, even for
    # the zero-todos edge case (Gmail connected but triage found nothing
    # important AND no focus set).
    await _emit_stage(
        user_id,
        OnboardingStage.TODOS_READY,
        {"todos": todos},
    )
    return todos


async def _run_workflows(
    user_id: str,
    profession: str,
    has_gmail: bool,
    focus: str,
    triage_future: asyncio.Task[Optional[InboxTriage]],
    writing_style_future: asyncio.Task[Optional[WritingStyleProfile]],
) -> list[dict]:
    triage, writing_style = await asyncio.gather(triage_future, writing_style_future)

    t0 = time.monotonic()
    try:
        workflows = await _create_onboarding_workflows(
            user_id, profession, has_gmail, focus, triage, writing_style
        )
    except Exception as e:
        log.error(f"[intelligence] workflows failed: {e}", exc_info=True)
        workflows = []

    log.info(
        f"[intelligence:timing] workflows: {time.monotonic() - t0:.1f}s "
        f"({len(workflows)} workflows)"
    )
    await _emit_stage(
        user_id,
        OnboardingStage.WORKFLOWS_READY,
        {"workflows": workflows},
    )
    return workflows


async def _run_holo_card(
    user_id: str,
    user_doc: dict,
    profession: str,
    focus: str,
    triage_future: asyncio.Task[Optional[InboxTriage]],
    writing_style_future: asyncio.Task[Optional[WritingStyleProfile]],
    social_profiles_future: asyncio.Task[list[SocialProfile]],
) -> None:
    triage, writing_style, social_profiles = await asyncio.gather(
        triage_future, writing_style_future, social_profiles_future
    )

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
        context_summary = "\n".join(context_parts)

        metadata = await get_user_metadata(user_id, user=user_doc)
        card_design = generate_profile_card_design()
        phrase, bio_result = await asyncio.gather(
            generate_personality_phrase(user_id, context_summary, profession),
            generate_user_bio(user_id, context_summary, user=user_doc),
        )
        user_bio, bio_status = bio_result
        workflow_ids = await suggest_workflows_via_rag(user_id, 4)
        await save_personalization_data(
            user_id,
            card_design["house"],
            phrase,
            user_bio,
            bio_status,
            workflow_ids,
            metadata["account_number"],
            metadata["member_since"],
            card_design["overlay_color"],
            card_design["overlay_opacity"],
        )
        log.info(
            f"[intelligence:timing] holo_card: {time.monotonic() - t0:.1f}s "
            f"(house={card_design['house']}, bio_status={bio_status})"
        )
    except Exception as e:
        log.error(f"[intelligence] holo_card failed: {e}", exc_info=True)

    await _emit_stage(user_id, OnboardingStage.HOLO_READY, {})


# ── Terminal helpers ─────────────────────────────────────────────────────────


async def _seed_conversation(user_id: str, first_message: str) -> Optional[str]:
    t0 = time.monotonic()
    try:
        cid = await seed_onboarding_conversation(
            user_id=user_id, first_message=first_message
        )
    except Exception as e:
        log.error(f"[intelligence] seed_conversation failed: {e}", exc_info=True)
        return None
    log.info(f"[intelligence:timing] seed_conversation: {time.monotonic() - t0:.1f}s")
    return cid


async def _persist_profiles(
    user_id: str,
    writing_style: Optional[WritingStyleProfile],
    triage: Optional[InboxTriage],
    social_profiles: list[SocialProfile],
) -> None:
    """Persist writing style, triage summary, and social profiles.

    Preserves two non-negotiable user-edit guards:
    - Writing style writes only sub-fields (never the whole object) so
      user_edited_summary is never clobbered.
    - Social profiles are only written if the user has not already confirmed
      them via POST /social-profiles ({"$exists": False} filter).
    """
    update_fields: dict = {}
    if writing_style:
        update_fields["onboarding.writing_style.summary"] = writing_style.summary
        update_fields["onboarding.writing_style.example"] = writing_style.example
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

    if social_profiles:
        try:
            # Only write auto-extracted profiles if the user hasn't already
            # confirmed them via POST /social-profiles.  The field may be
            # absent, null, or an empty list after initial onboarding — all
            # three mean "not yet confirmed by the user".
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
            log.error(
                f"[intelligence] persist social_profiles failed: {e}", exc_info=True
            )


# ── Todo creation helpers ────────────────────────────────────────────────────


async def _create_focus_todos(
    user_id: str,
    name: str,
    profession: str,
    focus: str,
) -> list[dict]:
    """Create 3 GAIA-actionable todos based on user's stated focus via LLM."""
    prompt = FOCUS_TODOS_PROMPT.format(
        name=name,
        profession=profession,
        focus=focus,
        format_instructions="Return a JSON object with a 'todos' key containing a list of 3 todo title strings.",
    )

    try:
        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        structured_llm = llm.with_structured_output(_FocusTodoList)
        parsed: _FocusTodoList = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

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
                log.warning(f"[intelligence] Failed to create focus todo: {e}")
                return None

        results = await asyncio.gather(*[_create_one(t) for t in parsed.todos[:3]])
        return [r for r in results if r is not None]

    except Exception as e:
        log.warning(f"[intelligence] _create_focus_todos failed: {e}")
        return []


async def _create_todos_from_triage(
    user_id: str,
    triage: InboxTriage,
    profession: str = "",
    focus: str = "",
) -> list[dict]:
    """Create GAIA-actionable todos from important emails using structured LLM output."""
    emails_context = "\n".join(
        f"- From: {e.sender} | Subject: {e.subject} | Why important: {e.why_important}"
        for e in triage.important_emails[:8]
    )

    prompt = TRIAGE_TODOS_PROMPT.format(
        emails_context=emails_context,
        profession=profession or "not specified",
        focus=focus or "not specified",
        format_instructions="Return a JSON object with a 'todos' key containing a list of todo objects, each with 'title', 'description', 'source_sender', and 'source_subject'.",
    )

    try:
        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        structured_llm = llm.with_structured_output(_TodoListFromEmails)
        parsed: _TodoListFromEmails = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

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
                if spec.source_sender or spec.source_subject:
                    todo_dict["source_email"] = {
                        "sender": spec.source_sender,
                        "subject": spec.source_subject,
                    }
                return todo_dict
            except Exception as e:
                log.warning(f"[intelligence] Failed to create todo: {e}")
                return None

        results = await asyncio.gather(*[_create_one(s) for s in parsed.todos[:3]])
        created = [r for r in results if r is not None]
        log.info(
            f"[intelligence] Created {len(created)} LLM-generated todos from triage"
        )
        return created

    except Exception as e:
        log.warning(f"[intelligence] LLM todo generation failed: {e}")
        return []


# ── Workflow creation helpers ────────────────────────────────────────────────


async def _create_onboarding_workflows(
    user_id: str,
    profession: str,
    has_gmail: bool,
    focus: str = "",
    triage: Optional[InboxTriage] = None,
    writing_style: Optional[WritingStyleProfile] = None,
) -> list[dict]:
    """Create 2 LLM-generated workflows tailored to the user's inbox context.

    Gmail system workflow provisioning runs as a separate root task in the
    orchestrator — not here.
    """
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

    try:
        prompt = WORKFLOW_CREATION_PROMPT.format(
            profession=profession or "professional",
            focus=focus or "not specified",
            has_gmail=has_gmail,
            inbox_patterns=inbox_patterns,
            email_senders_summary=email_senders_summary,
            writing_style_summary=writing_style_summary,
        )
        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        structured_llm = llm.with_structured_output(_WorkflowList)
        parsed: _WorkflowList = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )
        created: list[dict] = []
        for spec in parsed.workflows[:2]:
            try:
                safe_title = spec.title[:80]
                safe_desc = spec.description[:500]
                request = CreateWorkflowRequest(
                    title=safe_title,
                    description=safe_desc,
                    prompt=safe_desc,
                    trigger_config=TriggerConfig(type=TriggerType.SCHEDULE),
                    generate_immediately=False,
                )
                workflow = await WorkflowService.create_workflow(request, user_id)
                created.append(
                    {
                        "id": str(workflow.id),
                        "title": safe_title,
                        "description": safe_desc,
                        "categories": spec.categories[:3],
                    }
                )
            except Exception as e:
                log.warning(f"[intelligence] Failed to create workflow from spec: {e}")
        return created
    except Exception as e:
        log.warning(f"[intelligence] LLM workflow creation failed, using fallback: {e}")
        return await _create_fallback_workflow(user_id, profession, focus)


async def _create_fallback_workflow(
    user_id: str,
    profession: str,
    focus: str = "",
) -> list[dict]:
    """Fallback: create one generic daily briefing workflow when LLM fails."""
    title = "Daily Briefing"
    description = (
        f"Every morning, summarize unread emails by priority, today's meetings, and open todos. "
        f"Focus: {focus[:100]}."
        if focus
        else "Every morning at 9am, summarize unread emails by priority, today's meetings, and open todos."
    )
    try:
        request = CreateWorkflowRequest(
            title=title,
            description=description,
            prompt=description,
            trigger_config=TriggerConfig(type=TriggerType.SCHEDULE),
            generate_immediately=False,
        )
        workflow = await WorkflowService.create_workflow(request, user_id)
        return [{"id": str(workflow.id), "title": title, "description": description}]
    except Exception as e:
        log.warning(f"[intelligence] Fallback workflow creation failed: {e}")
        return []
