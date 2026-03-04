"""
Gmail system workflow definitions.

These are auto-provisioned when a user connects Gmail.
Each tuple is (system_workflow_key, factory function) — factories are called at
provisioning time so each user gets unique step IDs rather than sharing module-load IDs.
"""

from collections.abc import Callable
from uuid import uuid4

from app.models.trigger_configs import GmailPollInboxConfig
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)


def _email_intelligence() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Inbox Triage",
        description="Scans new emails, triages by importance, and creates todos for action items.",
        prompt=(
            "Triage the new inbox emails provided by the trigger. "
            "Classify each as spam, transactional, newsletter, informational, important, or action-required. "
            "Skip spam, transactional, and newsletters entirely. "
            "For important or action-required emails: extract action items, deadlines, and urgency "
            "(critical/high/normal). Create a todo for each action item. "
            "Search the web and user memory for relevant context on referenced topics or senders. "
            "Compile a concise briefing for the user covering what was processed, what needs attention, "
            "and what todos were created."
        ),
        is_system_workflow=True,
        source_integration="gmail",
        system_workflow_key="gmail:email_intelligence",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_poll_inbox",
            enabled=True,
            trigger_data=GmailPollInboxConfig(interval=15),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Classify the email",
                category="gmail",
                description=(
                    "Read the email. Classify as: spam, transactional/oauth, newsletter, "
                    "informational (FYI only), important, or action-required. "
                    "If spam, transactional, or newsletter — stop, do nothing."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Extract action items and urgency",
                category="gaia",
                description=(
                    "For important or action-required emails: extract concrete action items, "
                    "deadlines, and decisions the user needs to make. "
                    "Determine urgency: critical, high, or normal. "
                    "For informational emails: write a 1-sentence summary only."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Research and prepare context",
                category="todos",
                description=(
                    "For action-required emails: if the email involves a project, topic, "
                    "or assignment — search web and memory for relevant background. "
                    "Create a todo for each concrete action item. "
                    "If from a person, search memory for past interactions with them."
                ),
            ),
        ],
    )


def _smart_reply_drafts() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Auto-Draft Replies",
        description="Drafts replies for emails that need a response. You always approve before sending.",
        prompt=(
            "Check the new inbox emails from the trigger for ones that need a reply. "
            "Skip newsletters, automated notifications, transactional emails, CC-only threads, "
            "and threads the user already replied to. "
            "Draft replies for direct questions, explicit requests, meeting invites, and introductions. "
            "Search user memory for sender context and the user's writing style. "
            "Write concise replies matching the original tone. If the request is ambiguous, "
            "draft a clarifying reply instead of guessing. "
            "Save as Gmail drafts — never send directly. "
            "Send the user a summary of drafts created with sender and subject for each."
        ),
        is_system_workflow=True,
        source_integration="gmail",
        system_workflow_key="gmail:smart_reply_drafts",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_poll_inbox",
            enabled=True,
            trigger_data=GmailPollInboxConfig(interval=30),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Decide if a reply is warranted",
                category="gmail",
                description=(
                    "Read the email. Determine if a reply is expected. "
                    "Skip if: newsletter, marketing, automated notification, user is cc'd only, "
                    "no direct question or request, or thread already has a reply from user. "
                    "Draft only for: direct questions, requests, meeting invites, introductions."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Draft the reply",
                category="gaia",
                description=(
                    "Search memory for the sender's context and the user's writing style. "
                    "Write a concise, professional reply addressing the email's ask. "
                    "For ambiguous requests, write a brief clarifying reply instead of guessing. "
                    "Save as a Gmail draft — do NOT send."
                ),
            ),
        ],
    )


GMAIL_SYSTEM_WORKFLOWS: list[tuple[str, Callable[[], CreateWorkflowRequest]]] = [
    ("gmail:email_intelligence", _email_intelligence),
    ("gmail:smart_reply_drafts", _smart_reply_drafts),
]
