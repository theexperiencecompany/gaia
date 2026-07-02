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
        description="Daily digest: triages the last day's emails and creates todos for action items.",
        prompt=(
            "Fetch the emails that arrived in the user's Gmail inbox over the last 24 hours. "
            "Classify each as spam, transactional, newsletter, informational, important, or action-required. "
            "Skip spam, transactional, and newsletters entirely. "
            "For important or action-required emails: extract action items, deadlines, and urgency "
            "(critical/high/normal). Create a todo for each action item. "
            "Search the web and user memory for relevant context on referenced topics or senders. "
            "Compile ONE concise daily briefing covering what came in, what needs attention, "
            "and what todos were created."
        ),
        is_system_workflow=True,
        source_integration="gmail",
        system_workflow_key="gmail:email_intelligence",
        # Daily digest at 08:00 in the user's timezone (stamped by the provisioner):
        # one batched triage run instead of a full agent run per inbound email.
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression="0 8 * * *",
            enabled=True,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Fetch the last day's emails",
                category="gmail",
                description=(
                    "Fetch inbox emails received in the last 24 hours. "
                    "Classify each as: spam, transactional/oauth, newsletter, "
                    "informational (FYI only), important, or action-required. "
                    "Drop spam, transactional, and newsletters from further processing."
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
                title="Create todos and compile the briefing",
                category="todos",
                description=(
                    "Create a todo for each concrete action item (search web/memory for "
                    "background on referenced projects or senders where useful). "
                    "Then compile one concise briefing: what came in, what needs attention, "
                    "and which todos were created."
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
