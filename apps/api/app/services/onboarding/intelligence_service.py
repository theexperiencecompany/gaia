"""
OnboardingIntelligenceService — orchestrates the new onboarding pipeline.

Phase 1 (parallel, 5-45%):
  - fetch_emails_for_onboarding (1 month received)
  - learn_writing_style (last 100 sent)
  - parse_company_url (if provided)
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
from typing import Any, Coroutine, Optional

from bson import ObjectId
from shared.py.wide_events import log

from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import users_collection
from app.agents.memory.email_processor import (
    fetch_emails_for_onboarding,
    process_gmail_to_memory,
)
from app.models.onboarding_models import (
    CompanyProfile,
    InboxTriage,
    SocialProfile,
    WritingStyleProfile,
)
from app.models.todo_models import Priority, TodoModel
from app.models.workflow_models import CreateWorkflowRequest, TriggerConfig, TriggerType
from app.services.composio.composio_service import get_composio_service
from app.services.onboarding.company_parser_service import parse_company_url
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


async def _emit_progress(
    user_id: str,
    stage: str,
    message: str,
    progress: int,
) -> None:
    """Emit a WebSocket progress event to the user."""
    try:
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "personalization_progress",
                "data": {
                    "stage": stage,
                    "message": message,
                    "progress": progress,
                },
            },
        )
    except Exception as e:
        log.warning(f"[intelligence] Failed to emit progress: {e}")


async def process_onboarding_intelligence(user_id: str) -> None:
    """
    Main onboarding intelligence pipeline.
    Called as an ARQ background task after POST /onboarding.
    """
    log.set(user={"id": user_id})
    log.info(f"[intelligence] Starting onboarding intelligence for {user_id}")

    user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        log.error(f"[intelligence] User not found: {user_id}")
        return

    onboarding = user_doc.get("onboarding", {})
    name = user_doc.get("name", "there")
    profession = onboarding.get("preferences", {}).get("profession", "") or ""
    company_url: Optional[str] = onboarding.get("company_url")

    # Check Gmail availability
    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(
        ["gmail"], user_id
    )
    has_gmail = connection_status.get("gmail", False)

    # ── Phase 1: Parallel data gathering ──────────────────────────────────────

    await _emit_progress(user_id, "starting", "Setting up your GAIA", 5)

    emails: list[dict] = []
    writing_style: Optional[WritingStyleProfile] = None
    company_profile: Optional[CompanyProfile] = None
    social_profiles: list[SocialProfile] = []

    phase1_tasks: list[Coroutine[Any, Any, None]] = []

    if has_gmail:

        async def _fetch_emails() -> None:
            nonlocal emails
            await _emit_progress(user_id, "scanning_inbox", "Scanning your inbox", 10)
            fetched = await fetch_emails_for_onboarding(user_id, months=1)
            emails = fetched
            count = len(fetched)
            await _emit_progress(
                user_id, "scanning_inbox", f"{count} emails scanned", 25
            )

        async def _learn_style() -> None:
            nonlocal writing_style
            writing_style = await learn_writing_style(user_id)

        async def _store_to_memory() -> None:
            # Existing pipeline — store emails to mem0
            await process_gmail_to_memory(user_id)

        phase1_tasks.extend([_fetch_emails(), _learn_style(), _store_to_memory()])

    if company_url:

        async def _parse_company() -> None:
            nonlocal company_profile
            await _emit_progress(
                user_id, "parsing_company", "Reading your company site", 30
            )
            company_profile = await parse_company_url(company_url)  # type: ignore[arg-type]

        phase1_tasks.append(_parse_company())

    # Always run personalization (holo card, bio, house) in parallel
    async def _run_personalization() -> None:
        await process_post_onboarding_personalization(user_id)

    phase1_tasks.append(_run_personalization())

    await asyncio.gather(*phase1_tasks, return_exceptions=True)

    # Extract social profiles from fetched emails (CPU-only, no I/O)
    if emails:
        social_profiles = extract_social_profiles(emails)

    # ── Phase 2: Triage + todos + workflows ───────────────────────────────────

    await _emit_progress(user_id, "triaging", "Triaging by importance", 50)

    triage: Optional[InboxTriage] = None
    created_todos: list[dict] = []
    created_workflows: list[dict] = []

    if emails:
        triage = await triage_inbox(user_id, emails)
        if triage:
            unread_count = triage.total_unread
            important_count = len(triage.important_emails)
            await _emit_progress(
                user_id,
                "triaging",
                f"{unread_count} unread, {important_count} need attention",
                65,
            )

            await _emit_progress(user_id, "creating_todos", "Creating action items", 68)
            created_todos = await _create_todos_from_triage(user_id, triage)
            await _emit_progress(
                user_id,
                "creating_todos",
                f"{len(created_todos)} action items created",
                72,
            )

    await _emit_progress(user_id, "creating_workflows", "Setting up automations", 75)
    created_workflows = await _create_onboarding_workflows(
        user_id, profession, has_gmail
    )
    await _emit_progress(
        user_id,
        "creating_workflows",
        f"{len(created_workflows)} automations ready",
        85,
    )

    # ── Phase 3: Generate first message + seed conversation ───────────────────

    await _emit_progress(user_id, "preparing", "Preparing your workspace", 90)

    first_message = await generate_first_message(
        user_id=user_id,
        name=name,
        profession=profession,
        company_profile=company_profile,
        triage=triage,
        created_todos=created_todos,
        created_workflows=created_workflows,
        social_profiles=[p.model_dump() for p in social_profiles],
        writing_style=writing_style,
    )

    conversation_id = await seed_onboarding_conversation(
        user_id=user_id,
        first_message=first_message,
    )

    # Persist writing style and company profile to user doc
    update_fields: dict = {}
    if writing_style:
        update_fields["onboarding.writing_style"] = writing_style.model_dump()
    if company_profile:
        update_fields["onboarding.company_profile"] = company_profile.model_dump()
    if social_profiles:
        update_fields["onboarding.social_profiles"] = [
            p.model_dump() for p in social_profiles
        ]
    if conversation_id:
        update_fields["onboarding.first_message_conversation_id"] = conversation_id

    if update_fields:
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_fields},
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

    log.info(f"[intelligence] Completed onboarding intelligence for {user_id}")


async def _create_todos_from_triage(
    user_id: str,
    triage: InboxTriage,
) -> list[dict]:
    """Create todos from important emails in the triage result."""
    created = []
    for email in triage.important_emails[:5]:  # Cap at 5 todos
        try:
            todo = TodoModel(
                title=email.subject[:100],
                description=f"From {email.sender}: {email.why_important}",
                labels=["onboarding"],
                priority=Priority.MEDIUM,
                project_id=None,
            )
            result = await TodoService.create_todo(todo, user_id)
            created.append({"id": str(result.id), "title": email.subject[:100]})
        except Exception as e:
            log.warning(f"[intelligence] Failed to create todo: {e}")
    return created


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
) -> list[dict]:
    """Provision system workflows for Gmail (if connected) and one profession-specific workflow."""
    created = []

    if has_gmail:
        try:
            await provision_system_workflows(user_id, "gmail", "Gmail")
            created.append({"title": "Gmail System Workflows"})
        except Exception as e:
            log.warning(f"[intelligence] Failed to provision Gmail workflows: {e}")

    # Profession-specific workflow
    profession_key = profession.lower() if profession else ""
    config = _PROFESSION_WORKFLOW_MAP.get(profession_key)

    if not config:
        config = (
            "Daily Briefing",
            "Every morning at 9am, summarize unread emails by priority, today's meetings, and open todos into a concise daily brief.",
        )

    title, description = config

    try:
        request = CreateWorkflowRequest(
            title=title,
            description=description,
            prompt=description,
            trigger_config=TriggerConfig(type=TriggerType.SCHEDULE),
            generate_immediately=False,
        )
        workflow = await WorkflowService.create_workflow(request, user_id)
        created.append({"id": str(workflow.id), "title": title})
    except Exception as e:
        log.warning(f"[intelligence] Failed to create profession workflow: {e}")

    return created
