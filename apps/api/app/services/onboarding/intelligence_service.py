"""
OnboardingIntelligenceService — orchestrates the onboarding pipeline.

Phase 1 (parallel, 5-45%):
  - fetch_emails_for_onboarding (1 month received)
  - learn_writing_style (last 100 sent)
  - process_gmail_emails_to_memory (existing pipeline)
  - _run_holo_card (house, bio, personality phrase, card design)

Phase 2 (sequential, 50-85%):
  - triage_inbox
  - create todos from important emails
  - create 2 LLM-generated workflows using inbox context + profile (+ provision Gmail system workflows)

Phase 3 (90-100%):
  - generate_first_message (now receives created_workflows)
  - seed_onboarding_conversation
"""

import asyncio
import time
from typing import Any, Coroutine, Optional

from bson import ObjectId
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import (
    FOCUS_TODOS_PROMPT,
    TRIAGE_TODOS_PROMPT,
    WORKFLOW_CREATION_PROMPT,
)
from app.core.lazy_loader import providers
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import users_collection
from app.agents.memory.email_processor import (
    fetch_emails_for_onboarding,
    process_gmail_to_memory,
)
from app.constants.email import ONBOARDING_EMAIL_SCAN_LIMIT
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
    _canonicalize_social_url,
    extract_social_profiles_smart,
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


async def _emit_progress(
    user_id: str,
    stage: str,
    message: str,
    progress: int,
    results: Optional[dict] = None,
    details: Optional[dict] = None,
) -> None:
    """Emit a WebSocket progress event to the user."""
    try:
        payload: dict = {
            "stage": stage,
            "message": message,
            "progress": progress,
        }
        if results is not None:
            payload["results"] = results
        if details is not None:
            payload["details"] = details
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={"type": "personalization_progress", "data": payload},
        )
    except Exception as e:
        log.warning(f"[intelligence] Failed to emit progress: {e}")


async def process_onboarding_intelligence(user_id: str) -> None:
    """
    Main onboarding intelligence pipeline.
    Called as an ARQ background task after POST /onboarding.
    """
    log.set(user={"id": user_id})
    pipeline_start = time.monotonic()
    log.info(f"[intelligence] Starting onboarding intelligence for {user_id}")

    user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        log.error(f"[intelligence] User not found: {user_id}")
        return

    onboarding = user_doc.get("onboarding", {})
    name = user_doc.get("name", "there")
    profession = onboarding.get("preferences", {}).get("profession", "") or ""
    focus: str = onboarding.get("focus", "") or ""
    # Check Gmail availability
    t_gmail_check = time.monotonic()
    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(
        ["gmail"], user_id
    )
    has_gmail = connection_status.get("gmail", False)
    log.info(
        f"[intelligence:timing] gmail_check: {time.monotonic() - t_gmail_check:.1f}s (has_gmail={has_gmail})"
    )

    # ── Phase 1: Parallel data gathering ──────────────────────────────────────

    await _emit_progress(user_id, "starting", "Setting up your GAIA", 5)

    emails: list[dict] = []
    writing_style: Optional[WritingStyleProfile] = None
    social_profiles: list[SocialProfile] = []

    phase1_tasks: list[Coroutine[Any, Any, None]] = []

    if has_gmail:

        async def _fetch_emails() -> None:
            nonlocal emails
            t0 = time.monotonic()
            await _emit_progress(user_id, "scanning_inbox", "Scanning your inbox", 10)

            async def _on_batch(current: int) -> None:
                await _emit_progress(
                    user_id,
                    "scanning_inbox",
                    f"Scanning your inbox... {current} emails",
                    10,
                    details={"current": current},
                )

            fetched = await fetch_emails_for_onboarding(
                user_id,
                months=1,
                max_total=ONBOARDING_EMAIL_SCAN_LIMIT,
                on_batch=_on_batch,
            )
            emails = fetched
            count = len(fetched)
            log.info(
                f"[intelligence:timing] fetch_emails: {time.monotonic() - t0:.1f}s ({count} emails)"
            )
            await _emit_progress(
                user_id,
                "scanning_inbox",
                f"{count} emails scanned",
                25,
                results={"email_count": count},
            )

        async def _learn_style() -> None:
            nonlocal writing_style
            t0 = time.monotonic()
            writing_style = await learn_writing_style(user_id, profession=profession)
            log.info(
                f"[intelligence:timing] learn_writing_style: {time.monotonic() - t0:.1f}s"
            )
            await _emit_progress(
                user_id,
                "learning_style",
                "Writing style learned",
                28,
                results={
                    "style_summary": writing_style.summary
                    if writing_style and writing_style.summary
                    else "",
                    "example": writing_style.example
                    if writing_style and writing_style.example
                    else "",
                },
            )

        memory_result: dict = {}

        async def _store_to_memory() -> None:
            nonlocal memory_result
            t0 = time.monotonic()
            memory_result = await process_gmail_to_memory(user_id)
            log.info(
                f"[intelligence:timing] store_to_memory: {time.monotonic() - t0:.1f}s"
            )

        phase1_tasks.extend([_fetch_emails(), _learn_style(), _store_to_memory()])

    # Holo card generation moved to Phase 2 (needs triage data)

    phase1_start = time.monotonic()
    phase1_results = await asyncio.gather(*phase1_tasks, return_exceptions=True)
    log.info(
        f"[intelligence:timing] Phase 1 total: {time.monotonic() - phase1_start:.1f}s"
    )
    for i, result in enumerate(phase1_results):
        if isinstance(result, Exception):
            log.error(
                f"[intelligence] Phase 1 task {i} failed: {result}", exc_info=result
            )

    # Use Track B (LLM-based) profile results, then fill gaps with smart Track A
    if has_gmail:
        track_b_profiles = memory_result.get("extracted_profiles", [])
        if track_b_profiles:
            # Canonicalize Track B URLs before dedup
            social_profiles = [
                SocialProfile(
                    platform=p["platform"],
                    url=_canonicalize_social_url(p["url"]),
                )
                for p in track_b_profiles
            ]

        # Dedup Track B by platform (keep first)
        seen_platforms: set[str] = set()
        deduped_b: list[SocialProfile] = []
        for p in social_profiles:
            if p.platform not in seen_platforms:
                seen_platforms.add(p.platform)
                deduped_b.append(p)
        social_profiles = deduped_b

        # Fill gaps with smart Track A extraction
        if emails:
            user_email: str | None = user_doc.get("email")
            track_b_platforms = {p.platform for p in social_profiles}
            track_a = await extract_social_profiles_smart(emails, name, user_email)
            for p in track_a:
                if p.platform not in track_b_platforms:
                    social_profiles.append(p)
                    track_b_platforms.add(p.platform)

    if social_profiles:
        await _emit_progress(
            user_id,
            "finding_profiles",
            f"Found {len(social_profiles)} social profiles",
            45,
            results={
                "profiles": [
                    {"platform": p.platform, "url": p.url} for p in social_profiles[:8]
                ]
            },
        )

    # ── Phase 2: Triage + todos + workflows ───────────────────────────────────
    phase2_start = time.monotonic()
    await _emit_progress(user_id, "triaging", "Triaging by importance", 50)

    triage: Optional[InboxTriage] = None
    created_todos: list[dict] = []
    created_workflows: list[dict] = []

    if emails:
        t_triage = time.monotonic()
        triage = await triage_inbox(user_id, emails, profession=profession, focus=focus)
        log.info(
            f"[intelligence:timing] triage_inbox: {time.monotonic() - t_triage:.1f}s"
        )
        if triage:
            unread_count = triage.total_unread
            important_count = len(triage.important_emails)
            await _emit_progress(
                user_id,
                "triaging",
                f"{unread_count} unread, {important_count} need attention",
                65,
                results={
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
                },
            )

            await _emit_progress(user_id, "creating_todos", "Creating action items", 68)
            t_todos = time.monotonic()
            created_todos = await _create_todos_from_triage(
                user_id, triage, profession=profession, focus=focus
            )
            log.info(
                f"[intelligence:timing] create_todos: {time.monotonic() - t_todos:.1f}s ({len(created_todos)} todos)"
            )
            await _emit_progress(
                user_id,
                "creating_todos",
                f"{len(created_todos)} action items created",
                72,
                results={"todos": created_todos},
            )

    # No Gmail but user stated a focus — create focus-based todos
    if not emails and focus:
        await _emit_progress(user_id, "creating_todos", "Creating action items", 68)
        t_focus_todos = time.monotonic()
        created_todos = await _create_focus_todos(user_id, name, profession, focus)
        log.info(
            f"[intelligence:timing] create_focus_todos: {time.monotonic() - t_focus_todos:.1f}s ({len(created_todos)} todos)"
        )
        if created_todos:
            await _emit_progress(
                user_id,
                "creating_todos",
                f"{len(created_todos)} action items created",
                72,
                results={"todos": created_todos},
            )

    # Create workflows after triage — use inbox context for specificity
    await _emit_progress(user_id, "creating_workflows", "Setting up automations", 75)
    t_wf = time.monotonic()
    try:
        created_workflows = await _create_onboarding_workflows(
            user_id, profession, has_gmail, focus, triage, writing_style
        )
    except Exception as e:
        log.warning(f"[intelligence] Workflow creation failed: {e}")
        created_workflows = []
    log.info(
        f"[intelligence:timing] create_workflows: {time.monotonic() - t_wf:.1f}s ({len(created_workflows)} workflows)"
    )
    await _emit_progress(
        user_id,
        "creating_workflows",
        f"{len(created_workflows)} automations ready",
        80,
        results={"workflows": created_workflows},
    )

    # Holo card generation — uses triage data instead of raw memories
    t_holo = time.monotonic()
    try:
        # Build structured context from pipeline results
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
            f"[intelligence:timing] holo_card: {time.monotonic() - t_holo:.1f}s "
            f"(house={card_design['house']}, bio_status={bio_status})"
        )
    except Exception as e:
        log.error(f"[intelligence] Holo card generation failed: {e}", exc_info=True)

    await _emit_progress(user_id, "building_profile", "Building your profile", 88)
    log.info(
        f"[intelligence:timing] Phase 2 total: {time.monotonic() - phase2_start:.1f}s"
    )

    # ── Phase 3: First message + seed conversation ────────────────────────────
    phase3_start = time.monotonic()
    await _emit_progress(user_id, "preparing", "Preparing your workspace", 90)

    t_msg = time.monotonic()
    first_message = await generate_first_message(
        user_id=user_id,
        name=name,
        profession=profession,
        triage=triage,
        created_todos=created_todos,
        created_workflows=created_workflows,
        social_profiles=[p.model_dump() for p in social_profiles],
        writing_style=writing_style,
        focus=focus,
    )
    log.info(
        f"[intelligence:timing] generate_first_message: {time.monotonic() - t_msg:.1f}s"
    )

    # Persist writing style, social profiles, and triage in parallel with seeding.
    # Writing style is written to sub-fields only (never the whole object) so that
    # any user_edited_summary already saved via POST /writing-style is preserved.
    # Social profiles are only written if the user has not already confirmed them
    # via POST /social-profiles — prevents overwriting user edits made while the
    # pipeline was still running.
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

    async def _seed() -> Optional[str]:
        t0 = time.monotonic()
        cid = await seed_onboarding_conversation(
            user_id=user_id, first_message=first_message
        )
        log.info(
            f"[intelligence:timing] seed_conversation: {time.monotonic() - t0:.1f}s"
        )
        return cid

    async def _persist_profiles() -> None:
        if update_fields:
            await users_collection.update_one(
                {"_id": ObjectId(user_id)}, {"$set": update_fields}
            )
        # Only persist extracted social profiles if the user has not already
        # confirmed their own via POST /social-profiles (which sets the same field).
        if social_profiles:
            await users_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "onboarding.social_profiles": {"$exists": False},
                },
                {
                    "$set": {
                        "onboarding.social_profiles": [
                            p.model_dump() for p in social_profiles
                        ]
                    }
                },
            )

    conversation_id, _ = await asyncio.gather(_seed(), _persist_profiles())

    # Persist conversation_id separately (depends on seed result)
    if conversation_id:
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"onboarding.first_message_conversation_id": conversation_id}},
        )

    await _emit_progress(user_id, "complete", "Ready", 100)

    # Emit completion event
    await websocket_manager.broadcast_to_user(
        user_id=user_id,
        message={
            "type": "onboarding_intelligence_complete",
            "data": {
                "conversation_id": conversation_id,
            },
        },
    )

    log.info(
        f"[intelligence:timing] Phase 3: {time.monotonic() - phase3_start:.1f}s | "
        f"Pipeline total: {time.monotonic() - pipeline_start:.1f}s"
    )


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


async def _create_onboarding_workflows(
    user_id: str,
    profession: str,
    has_gmail: bool,
    focus: str = "",
    triage: Optional[InboxTriage] = None,
    writing_style: Optional[WritingStyleProfile] = None,
) -> list[dict]:
    """
    Create 2 LLM-generated workflows tailored to the user's inbox context and profile.
    Runs Gmail system workflow provisioning in parallel.
    """

    # Provision Gmail system workflows (fire-and-forget alongside LLM call)
    async def _provision_gmail() -> None:
        if not has_gmail:
            return
        try:
            await provision_system_workflows(user_id, "gmail", "Gmail")
        except Exception as e:
            log.warning(f"[intelligence] Failed to provision Gmail workflows: {e}")

    # Build context for LLM
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

    async def _create_llm_workflows() -> list[dict]:
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
                    log.warning(
                        f"[intelligence] Failed to create workflow from spec: {e}"
                    )
            return created
        except Exception as e:
            log.warning(
                f"[intelligence] LLM workflow creation failed, using fallback: {e}"
            )
            return await _create_fallback_workflow(user_id, profession, focus)

    workflows, _ = await asyncio.gather(_create_llm_workflows(), _provision_gmail())
    return workflows


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
