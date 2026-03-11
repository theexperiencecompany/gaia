"""
Gmail system workflow definitions.

These are auto-provisioned when a user connects Gmail.
Each tuple is (system_workflow_key, factory function) — factories are called at
provisioning time so each user gets unique step IDs rather than sharing module-load IDs.
"""

from collections.abc import Callable
from uuid import uuid4

from app.models.trigger_configs import GmailNewMessageConfig, GmailPollInboxConfig
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


def _inbox_cleanup_6h() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Inbox Cleanup (Every 6 Hours)",
        description=(
            "Organizes recent inbox emails using your preferred labels, "
            "archive rules, and starring rules."
        ),
        prompt=(
            "Run an inbox cleanup pass for emails from the last 6 hours. "
            "Activate the gmail-clean-inbox skill first and follow it. "
            "First, count unread inbox emails in the 6-hour window using "
            "GMAIL_GET_UNREAD_COUNT_WINDOW(hours=6) or a query fallback. "
            "Then fetch candidate message IDs with lightweight payloads using "
            "pagination (`max_results=20` + `next_page_token`) and process each "
            "page as a non-overlapping batch via spawn_subagent. "
            "Each spawned subagent must classify and apply all actions for its "
            "own batch in one pass (do not split label/archive/star into "
            "separate subagents). "
            "Pass relevant memory policy to each subagent: VIP senders, "
            "protected labels, and archive preferences. "
            "If the user already has a meaningful label/folder system, reuse it "
            "and do not create/rename/delete labels. Only use fallback labels "
            "when no usable structure exists. "
            "For HTML-heavy emails, reason on parsed plain text and note that "
            "content was parsed. "
            "Never delete emails. Never modify emails already starred by the "
            "user unless memory instructions explicitly allow it. "
            "Send a concise summary of actions taken."
        ),
        is_system_workflow=True,
        source_integration="gmail",
        system_workflow_key="gmail:inbox_cleanup_6h",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_poll_inbox",
            enabled=True,
            trigger_data=GmailPollInboxConfig(interval=360),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Load cleanup policy and current labels",
                category="gmail",
                description=(
                    "Read memory for cleanup preferences and VIP senders. "
                    "List labels, detect whether a user taxonomy already "
                    "exists, and set preserve vs fallback mode."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Count and batch unread emails in the last 6 hours",
                category="gmail",
                description=(
                    "Count unread in the 6-hour window, fetch candidate message "
                    "IDs in lightweight mode, split into non-overlapping "
                    "batches, and spawn subagents per batch."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Apply labels, archive, and stars safely per batch",
                category="gmail",
                description=(
                    "Each batch subagent should classify and apply final actions "
                    "for its own messages in one pass: keep important mail in "
                    "inbox, star urgent items, and archive low-value items. "
                    "Never delete."
                ),
            ),
        ],
    )


def _important_mail_alerts() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Important Mail Alerts",
        description=(
            "Watches each new email and notifies you immediately when it "
            "requires attention."
        ),
        prompt=(
            "When a new email arrives, determine whether it needs immediate "
            "attention. Use the trigger sender/subject/content preview first, "
            "and fetch more context only when uncertain. "
            "Search memory for VIP senders, urgency preferences, and topics "
            "the user cares about. "
            "Treat as important if it contains urgent deadlines, direct asks, "
            "security or financial risk, scheduling changes, or comes from a "
            "high-priority contact. "
            "For important emails, star the message, apply relevant labels, and "
            "send a concise alert with why it matters and the next best action. "
            "For low-value newsletters/promotions/automated updates, avoid noisy "
            "alerts and only apply lightweight organization when useful. "
            "Never auto-reply and never delete."
        ),
        is_system_workflow=True,
        source_integration="gmail",
        system_workflow_key="gmail:important_mail_alerts",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_new_message",
            enabled=True,
            trigger_data=GmailNewMessageConfig(),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Score urgency and importance",
                category="gmail",
                description=(
                    "Classify the incoming email by urgency and business impact "
                    "using sender, subject, and message preview."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Fetch context only when confidence is low",
                category="gmail",
                description=(
                    "If classification is uncertain, fetch the full message or "
                    "thread to improve accuracy before deciding."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Notify and organize important emails",
                category="gmail",
                description=(
                    "For important emails, star, label, and send a brief alert. "
                    "For low-signal emails, skip alerting."
                ),
            ),
        ],
    )


def _follow_up_watchdog_daily() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Follow-Up Watchdog",
        description=(
            "Runs daily to identify unresolved threads and tasks that need a follow-up."
        ),
        prompt=(
            "Run a daily follow-up check across recent email conversations. "
            "Scan the last 14 days for: unread important emails older than 48 "
            "hours, threads waiting on your reply, and threads where you are "
            "waiting on someone else with no response for multiple days. "
            "Search memory for active commitments and follow-up preferences. "
            "Create or update todos for concrete follow-ups with clear titles, "
            "urgency, and due dates. "
            "Send the user a concise digest grouped by waiting-for-reply, "
            "needs-your-reply, and overdue follow-ups. "
            "Do not send emails automatically."
        ),
        is_system_workflow=True,
        source_integration="gmail",
        system_workflow_key="gmail:follow_up_watchdog_daily",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_poll_inbox",
            enabled=True,
            trigger_data=GmailPollInboxConfig(interval=1440),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Find unresolved and stale conversations",
                category="gmail",
                description=(
                    "Identify threads that require follow-up or have stalled for "
                    "several days."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Create or update follow-up todos",
                category="todos",
                description=(
                    "Create one todo per actionable follow-up with due date and "
                    "priority."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Send a daily follow-up digest",
                category="gaia",
                description=(
                    "Summarize what needs follow-up and what can wait. Keep it "
                    "brief and actionable."
                ),
            ),
        ],
    )


GMAIL_SYSTEM_WORKFLOWS: list[tuple[str, Callable[[], CreateWorkflowRequest]]] = [
    ("gmail:email_intelligence", _email_intelligence),
    ("gmail:smart_reply_drafts", _smart_reply_drafts),
    ("gmail:inbox_cleanup_6h", _inbox_cleanup_6h),
    ("gmail:important_mail_alerts", _important_mail_alerts),
    ("gmail:follow_up_watchdog_daily", _follow_up_watchdog_daily),
]
