"""
OnboardingIntelligenceService — orchestrates the new onboarding pipeline.

Phase 1 (parallel, 5-45%):
  - fetch_emails_for_onboarding (1 month received)
  - learn_writing_style (last 100 sent)
  - process_gmail_emails_to_memory (existing pipeline)
  - process_post_onboarding_personalization (existing — holo card, bio, house)

Phase 2 (needs Phase 1 emails, 50-85%):
  - triage_inbox
  - create todos from important emails
  - provision Gmail system workflows (if connected)
  - create profession-specific workflow

Phase 3 (90-100%):
  - generate_first_message
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
)
from app.core.lazy_loader import providers
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import users_collection
from app.agents.memory.email_processor import (
    fetch_emails_for_onboarding,
    process_gmail_to_memory,
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
    process_post_onboarding_personalization,
)
from app.services.onboarding.social_profile_service import extract_social_profiles
from app.services.onboarding.writing_style_service import learn_writing_style
from app.services.system_workflows.provisioner import provision_system_workflows
from app.services.todos.todo_service import TodoService
from app.services.workflow.service import WorkflowService
from app.utils.seeding_utils import seed_onboarding_conversation


class _TodoSpec(BaseModel):
    title: str = Field(
        description="What GAIA will do — under 80 chars, starts with a verb"
    )
    description: str = Field(
        description="Context and what the output will be — 1-2 sentences"
    )


class _TodoListFromEmails(BaseModel):
    todos: list[_TodoSpec] = Field(
        description="List of GAIA-actionable todo items, max 5"
    )


class _FocusTodoList(BaseModel):
    todos: list[str] = Field(description="List of 3 GAIA-actionable todo titles")


async def _emit_progress(
    user_id: str,
    stage: str,
    message: str,
    progress: int,
    results: Optional[dict] = None,
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
            fetched = await fetch_emails_for_onboarding(user_id, months=1)
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
            writing_style = await learn_writing_style(user_id)
            log.info(
                f"[intelligence:timing] learn_writing_style: {time.monotonic() - t0:.1f}s"
            )
            await _emit_progress(
                user_id,
                "learning_style",
                "Writing style learned",
                28,
                results={
                    "style_summary": writing_style.summary[:200]
                    if writing_style and writing_style.summary
                    else ""
                },
            )

        async def _store_to_memory() -> None:
            t0 = time.monotonic()
            await process_gmail_to_memory(user_id)
            log.info(
                f"[intelligence:timing] store_to_memory: {time.monotonic() - t0:.1f}s"
            )

        phase1_tasks.extend([_fetch_emails(), _learn_style(), _store_to_memory()])

    # Always run personalization (holo card, bio, house) in parallel
    async def _run_personalization() -> None:
        t0 = time.monotonic()
        await process_post_onboarding_personalization(user_id)
        log.info(
            f"[intelligence:timing] run_personalization: {time.monotonic() - t0:.1f}s"
        )

    phase1_tasks.append(_run_personalization())

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

    # Extract social profiles from fetched emails (CPU-only, no I/O)
    if emails:
        social_profiles = extract_social_profiles(emails)
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

    # Start workflow creation in parallel — it doesn't depend on triage
    workflow_task = asyncio.create_task(
        _create_onboarding_workflows(user_id, profession, has_gmail, focus)
    )

    if emails:
        t_triage = time.monotonic()
        triage = await triage_inbox(user_id, emails)
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
            created_todos = await _create_todos_from_triage(user_id, triage)
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

    # Emit workflows progress
    await _emit_progress(user_id, "creating_workflows", "Setting up automations", 75)

    # Start first message generation in parallel with workflow await
    phase3_start = time.monotonic()
    await _emit_progress(user_id, "preparing", "Preparing your workspace", 90)

    t_msg = time.monotonic()
    first_message_task = asyncio.create_task(
        generate_first_message(
            user_id=user_id,
            name=name,
            profession=profession,
            triage=triage,
            created_todos=created_todos,
            created_workflows=[],  # Don't wait for workflows
            social_profiles=[p.model_dump() for p in social_profiles],
            writing_style=writing_style,
            focus=focus,
        )
    )

    # Await both in parallel
    try:
        created_workflows = await workflow_task
    except Exception as e:
        log.warning(f"[intelligence] Workflow creation failed: {e}")
        created_workflows = []

    await _emit_progress(
        user_id,
        "creating_workflows",
        f"{len(created_workflows)} automations ready",
        85,
        results={"workflows": created_workflows},
    )
    log.info(
        f"[intelligence:timing] Phase 2 total: {time.monotonic() - phase2_start:.1f}s"
    )

    first_message = await first_message_task
    log.info(
        f"[intelligence:timing] generate_first_message: {time.monotonic() - t_msg:.1f}s"
    )

    # Persist writing style and social profiles in parallel with seeding
    update_fields: dict = {}
    if writing_style:
        update_fields["onboarding.writing_style"] = writing_style.model_dump()
    if social_profiles:
        update_fields["onboarding.social_profiles"] = [
            p.model_dump() for p in social_profiles
        ]
    if triage:
        update_fields["onboarding.triage_summary"] = {
            "total_scanned": triage.total_scanned,
            "total_unread": triage.total_unread,
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
                todo = TodoModel(
                    title=title[:100],
                    description=f"Created from your focus: {focus[:100]}",
                    labels=["onboarding"],
                    priority=Priority.MEDIUM,
                    project_id=None,
                )
                result = await TodoService.create_todo(todo, user_id)
                return {"id": str(result.id), "title": title[:100]}
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
) -> list[dict]:
    """Create GAIA-actionable todos from important emails using structured LLM output."""
    emails_context = "\n".join(
        f"- From: {e.sender} | Subject: {e.subject} | Why important: {e.why_important}"
        for e in triage.important_emails[:8]
    )

    prompt = TRIAGE_TODOS_PROMPT.format(
        emails_context=emails_context,
        format_instructions="Return a JSON object with a 'todos' key containing a list of todo objects, each with 'title' and 'description'.",
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
                todo = TodoModel(
                    title=spec.title[:100],
                    description=spec.description[:500],
                    labels=["onboarding"],
                    priority=Priority.MEDIUM,
                    project_id=None,
                )
                result = await TodoService.create_todo(todo, user_id)
                return {"id": str(result.id), "title": spec.title[:100]}
            except Exception as e:
                log.warning(f"[intelligence] Failed to create todo: {e}")
                return None

        results = await asyncio.gather(*[_create_one(s) for s in parsed.todos[:5]])
        created = [r for r in results if r is not None]
        log.info(
            f"[intelligence] Created {len(created)} LLM-generated todos from triage"
        )
        return created

    except Exception as e:
        log.warning(f"[intelligence] LLM todo generation failed: {e}")
        return []


_PROFESSION_WORKFLOW_MAP: dict[str, tuple[str, str]] = {
    "founder": (
        "Daily Founder Briefing",
        "Every morning, scan inbox for investor and partner emails, research senders, and compile a prioritized briefing of what needs attention today.",
    ),
    "entrepreneur": (
        "Daily Founder Briefing",
        "Every morning, scan inbox for investor and partner emails, research senders, and compile a prioritized briefing of what needs attention today.",
    ),
    "developer": (
        "PR & Bug Triage",
        "When a customer bug report or PR review request arrives, extract the key details, check for related open issues, and create a structured todo with reproduction steps.",
    ),
    "engineer": (
        "PR & Bug Triage",
        "When a customer bug report or PR review request arrives, extract the key details, check for related open issues, and create a structured todo with reproduction steps.",
    ),
    "marketing": (
        "Daily Campaign Snapshot",
        "Every morning, scan inbox for platform notification emails, extract key metrics, and compile a performance snapshot.",
    ),
    "student": (
        "Deadline Tracker",
        "Monitor academic emails for deadlines, assignments, and professor updates. Create todos with reverse-planned subtasks when a new deadline is found.",
    ),
    "manager": (
        "Team Pulse",
        "Daily scan of team communication emails and threads. Flag blockers, action items awaiting your decision, and anything overdue.",
    ),
    "designer": (
        "Feedback Tracker",
        "Monitor client and stakeholder emails for design feedback. Create structured todos with feedback quotes and suggested next steps.",
    ),
    "sales": (
        "Pipeline Daily Brief",
        "Every morning, scan inbox for prospect and client emails, identify follow-ups needed, and compile a prioritized outreach list.",
    ),
}


async def _create_onboarding_workflows(
    user_id: str,
    profession: str,
    has_gmail: bool,
    focus: str = "",
) -> list[dict]:
    """Provision system workflows for Gmail (if connected) and one profession-specific workflow."""
    created: list[dict] = []

    profession_key = profession.lower() if profession else ""
    config = _PROFESSION_WORKFLOW_MAP.get(profession_key)
    if not config:
        config = (
            "Daily Briefing",
            "Every morning at 9am, summarize unread emails by priority, today's meetings, and open todos into a concise daily brief.",
        )
    title, description = config

    async def _provision_gmail() -> Optional[dict]:
        if not has_gmail:
            return None
        try:
            await provision_system_workflows(user_id, "gmail", "Gmail")
            return {"title": "Gmail System Workflows"}
        except Exception as e:
            log.warning(f"[intelligence] Failed to provision Gmail workflows: {e}")
            return None

    async def _create_profession_wf() -> Optional[dict]:
        try:
            request = CreateWorkflowRequest(
                title=title,
                description=description,
                prompt=description,
                trigger_config=TriggerConfig(type=TriggerType.SCHEDULE),
                generate_immediately=False,
            )
            workflow = await WorkflowService.create_workflow(request, user_id)
            return {"id": str(workflow.id), "title": title}
        except Exception as e:
            log.warning(f"[intelligence] Failed to create profession workflow: {e}")
            return None

    tasks: list[Any] = [_provision_gmail(), _create_profession_wf()]

    if not has_gmail and focus:
        focus_title = "Focus Workflow"
        focus_description = f"When working on: {focus[:200]}. Track progress, set reminders, and report back on completion."

        async def _create_focus_wf() -> Optional[dict]:
            try:
                request = CreateWorkflowRequest(
                    title=focus_title,
                    description=focus_description,
                    prompt=focus_description,
                    trigger_config=TriggerConfig(type=TriggerType.SCHEDULE),
                    generate_immediately=False,
                )
                workflow = await WorkflowService.create_workflow(request, user_id)
                return {
                    "id": str(workflow.id),
                    "title": focus_title,
                    "description": focus_description,
                }
            except Exception as e:
                log.warning(f"[intelligence] Failed to create focus workflow: {e}")
                return None

        tasks.append(_create_focus_wf())

    results = await asyncio.gather(*tasks)
    for r in results:
        if r is not None:
            created.append(r)
    return created
