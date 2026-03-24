"""Gmail system workflow definitions."""

from collections.abc import Callable
from uuid import uuid4

from app.models.trigger_configs import GmailPollInboxConfig
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)


def _inbox_intelligence() -> CreateWorkflowRequest:
    """Unified Gmail workflow for triage, drafting, and follow-ups."""

    return CreateWorkflowRequest(
        title="Inbox Intelligence",
        description=(
            "Every 15 minutes, triages recent inbox mail, drafts replies, and "
            "tracks follow-ups in one pass."
        ),
        prompt=(
            "Run a single Inbox Intelligence pass on the latest inbox activity. "
            "Analyze unread and newly updated threads from the last 48 hours first. "
            "Classify each email as spam/promotional, transactional, FYI, important, "
            "or action-required. Skip spam/promotional noise. "
            "For important and action-required emails, extract concrete tasks, due dates, "
            "and urgency (critical/high/normal), then create or update todos. "
            "If a message likely needs a reply, draft a concise response using sender "
            "context and user tone memory. Save drafts only; never send automatically. "
            "For urgent or high-impact items, star the email and include a short "
            "attention alert in the summary. "
            "Identify stale threads that still need user follow-up and add those as todos. "
            "Return one compact digest with: processed counts, urgent alerts, drafted replies, "
            "and follow-up tasks."
        ),
        is_system_workflow=True,
        source_integration="gmail",
        system_workflow_key="gmail:inbox_intelligence",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_poll_inbox",
            enabled=True,
            trigger_data=GmailPollInboxConfig(interval=15),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Collect and classify recent inbox activity",
                category="gmail",
                description=(
                    "Scan recent unread and active threads, then classify signal vs noise."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Extract actions and maintain todo list",
                category="todos",
                description=(
                    "Create or update todos for concrete asks, deadlines, and follow-ups."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Draft responses for reply-worthy emails",
                category="gmail",
                description=(
                    "Draft concise Gmail replies where a response is expected. Never send."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Highlight urgent items and summarize",
                category="gaia",
                description=(
                    "Star urgent emails and deliver one actionable digest of outcomes."
                ),
            ),
        ],
    )


def _inbox_cleanup_6h() -> CreateWorkflowRequest:
    """Batch cleanup workflow that runs every 6 hours."""

    return CreateWorkflowRequest(
        title="Inbox Cleanup (Every 6 Hours)",
        description=(
            "Organizes recent inbox emails using your preferred labels, "
            "archive rules, and starring rules."
        ),
        prompt=(
            "Run an inbox cleanup pass for emails from the last 6 hours. "
            "Activate the gmail-clean-inbox skill first and follow it. "
            "Count unread inbox emails in the 6-hour window first, then fetch "
            "candidate message IDs with pagination and process each page as a "
            "non-overlapping batch via spawn_subagent. "
            "Each batch subagent should classify and apply label/archive/star actions "
            "for its own messages in one pass. "
            "Reuse existing user label taxonomy when possible; avoid creating noisy labels. "
            "Never delete emails. "
            "Use cleaned plain-text content for reasoning and return a concise summary "
            "of actions taken."
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
                    "Read memory for cleanup preferences and VIP senders, then map "
                    "existing label taxonomy before actions."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Batch-process unread inbox emails",
                category="gmail",
                description=(
                    "Fetch unread candidates from the last 6 hours and process in "
                    "non-overlapping batches."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Apply organization actions safely",
                category="gmail",
                description=(
                    "Apply labels, archive low-value mail, and star urgent items. "
                    "Never delete."
                ),
            ),
        ],
    )


def _follow_up_watchdog_daily() -> CreateWorkflowRequest:
    """Daily workflow to detect and track unresolved follow-ups."""

    return CreateWorkflowRequest(
        title="Follow-Up Watchdog",
        description=(
            "Runs daily to identify unresolved threads and tasks that need a follow-up."
        ),
        prompt=(
            "Run a daily follow-up check across recent email conversations. "
            "Scan the last 14 days for unread important emails older than 48 hours, "
            "threads waiting on your reply, and threads where you are waiting on "
            "someone else with no response for multiple days. "
            "Search memory for active commitments and follow-up preferences. "
            "Create or update todos for concrete follow-ups with clear titles, urgency, "
            "and due dates. "
            "Use cleaned plain-text email content for reasoning and send a concise digest "
            "grouped by waiting-for-reply, needs-your-reply, and overdue follow-ups."
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
                    "Identify threads that require follow-up or appear stalled."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Create or update follow-up todos",
                category="todos",
                description=(
                    "Create one todo per actionable follow-up with due date and priority."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Send a daily follow-up digest",
                category="gaia",
                description=(
                    "Summarize what needs follow-up and what can wait. Keep it actionable."
                ),
            ),
        ],
    )


GMAIL_SYSTEM_WORKFLOWS: list[tuple[str, Callable[[], CreateWorkflowRequest]]] = [
    ("gmail:inbox_intelligence", _inbox_intelligence),
    ("gmail:inbox_cleanup_6h", _inbox_cleanup_6h),
    ("gmail:follow_up_watchdog_daily", _follow_up_watchdog_daily),
]
