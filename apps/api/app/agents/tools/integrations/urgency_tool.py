"""Cross-integration urgency aggregator tool.

Aggregates urgency signals across multiple integration context snapshots
into a single prioritized list of items needing attention.
"""

from typing import Literal

from composio import Composio
from composio.types import ExecuteRequestFn
from pydantic import BaseModel, ConfigDict, Field

UrgencyPriority = Literal["high", "medium", "low"]

_PRIORITY_ORDER: dict[UrgencyPriority, int] = {"high": 0, "medium": 1, "low": 2}


class SnapshotItem(BaseModel):
    """One listed item of another tool's snapshot — only the labels the aggregator quotes."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    name: str | None = None
    summary: str | None = None
    text: str | None = None
    overdue: bool | None = None


class IntegrationSnapshot(BaseModel):
    """One CUSTOM_GATHER_CONTEXT output, reduced to the keys the aggregator reads.

    Which branches fire depends on which keys the snapshot *carries*, not on
    their values (``model_fields_set``), so an integration reporting
    ``unread_count: 0`` is still recognised as that integration.
    """

    model_config = ConfigDict(extra="ignore")

    inbox_unread_count: int | None = None
    unread_count: int | None = None
    mentions: list[SnapshotItem] = Field(default_factory=list)
    overdue_issues: list[SnapshotItem] = Field(default_factory=list)
    events: list[SnapshotItem] = Field(default_factory=list)
    next_event: SnapshotItem | None = None
    notifications: list[SnapshotItem] = Field(default_factory=list)
    review_requests: list[SnapshotItem] = Field(default_factory=list)
    overdue_tasks: list[SnapshotItem] = Field(default_factory=list)
    urgent_tasks: list[SnapshotItem] = Field(default_factory=list)
    unread_chat_count: int | None = None
    unread_message_count: int | None = None

    def carries(self, *keys: str) -> bool:
        return any(key in self.model_fields_set for key in keys)


class UrgencyAggregatorInput(BaseModel):
    """Input for the urgency aggregator: a dict of integration snapshots."""

    snapshots: dict[str, IntegrationSnapshot] = Field(
        ...,
        description=(
            "Dict mapping integration name to its CUSTOM_GATHER_CONTEXT output. "
            "Example: {'gmail': {...}, 'slack': {...}, 'linear': {...}}"
        ),
    )


class UrgentItem(BaseModel):
    """One prioritized signal; ``details`` is only emitted by the branches that quote items."""

    integration: str
    type: str
    count: int
    priority: UrgencyPriority
    description: str
    details: list[str | None] = Field(default_factory=list)


def _event_label(event: SnapshotItem) -> str | None:
    if "summary" in event.model_fields_set:
        return event.summary
    return event.title if "title" in event.model_fields_set else ""


def _gmail_items(snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # Gmail: unread count (data is flat — inbox_unread_count at top level)
    if not snapshot.carries("inbox_unread_count", "unread_count"):
        return []
    unread = snapshot.inbox_unread_count or snapshot.unread_count or 0
    if unread <= 0:
        return []
    return [
        UrgentItem(
            integration="gmail",
            type="unread_emails",
            count=unread,
            priority="high" if unread > 20 else "medium",
            description=f"{unread} unread emails in inbox",
        )
    ]


def _slack_items(snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # Slack: unread mentions / messages
    if not snapshot.carries("mentions", "unread_count"):
        return []
    mentions_list = snapshot.mentions
    unread_count = snapshot.unread_count or 0
    if not (mentions_list or unread_count):
        return []
    return [
        UrgentItem(
            integration="slack",
            type="unread_messages",
            count=len(mentions_list) if mentions_list else unread_count,
            priority="high",
            description=(
                f"{len(mentions_list)} Slack @mentions"
                if mentions_list
                else f"{unread_count} unread Slack messages"
            ),
            details=[(m.text or "")[:80] for m in mentions_list[:3]],
        )
    ]


def _linear_items(snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # Linear: overdue issues
    if not (snapshot.carries("overdue_issues") and snapshot.overdue_issues):
        return []
    overdue = snapshot.overdue_issues
    return [
        UrgentItem(
            integration="linear",
            type="overdue_issues",
            count=len(overdue),
            priority="high",
            description=f"{len(overdue)} overdue Linear issues",
            details=[i.title for i in overdue[:3]],
        )
    ]


def _calendar_items(snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # Google Calendar: today's events
    if not snapshot.carries("events", "next_event"):
        return []
    if snapshot.events:
        event_list = snapshot.events
    elif snapshot.next_event:
        event_list = [snapshot.next_event]
    else:
        return []
    return [
        UrgentItem(
            integration="googlecalendar",
            type="upcoming_events",
            count=len(event_list),
            priority="medium",
            description=f"{len(event_list)} calendar events today",
            details=[_event_label(e) for e in event_list[:3]],
        )
    ]


def _github_items(snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # GitHub: notifications and review requests
    if not snapshot.carries("notifications", "review_requests"):
        return []
    items: list[UrgentItem] = []
    notif_count = len(snapshot.notifications)
    review_count = len(snapshot.review_requests)
    if notif_count > 0:
        items.append(
            UrgentItem(
                integration="github",
                type="unread_notifications",
                count=notif_count,
                priority="medium",
                description=f"{notif_count} unread GitHub notifications",
            )
        )
    if review_count > 0:
        items.append(
            UrgentItem(
                integration="github",
                type="review_requests",
                count=review_count,
                priority="high",
                description=f"{review_count} GitHub PRs awaiting your review",
                details=[pr.title or "" for pr in snapshot.review_requests[:3]],
            )
        )
    return items


def _task_items(integration_lower: str, snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # Asana / Todoist / ClickUp: overdue tasks
    overdue_tasks = snapshot.overdue_tasks
    if not overdue_tasks:
        # Try urgent_tasks for Google Tasks
        overdue_tasks = [t for t in snapshot.urgent_tasks if t.overdue]
    if not overdue_tasks:
        return []
    return [
        UrgentItem(
            integration=integration_lower,
            type="overdue_tasks",
            count=len(overdue_tasks),
            priority="high",
            description=f"{len(overdue_tasks)} overdue tasks in {integration_lower}",
            details=[t.name or t.title for t in overdue_tasks[:3]],
        )
    ]


def _teams_items(snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # Teams: unread chats
    if not snapshot.carries("unread_chat_count"):
        return []
    unread_chats = snapshot.unread_chat_count or 0
    if unread_chats <= 0:
        return []
    return [
        UrgentItem(
            integration="microsoft_teams",
            type="unread_chats",
            count=unread_chats,
            priority="medium",
            description=f"{unread_chats} unread Microsoft Teams chats",
        )
    ]


def _reddit_items(snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    # Reddit: unread messages
    if not snapshot.carries("unread_message_count"):
        return []
    unread_msgs = snapshot.unread_message_count or 0
    if unread_msgs <= 0:
        return []
    return [
        UrgentItem(
            integration="reddit",
            type="unread_messages",
            count=unread_msgs,
            priority="low",
            description=f"{unread_msgs} unread Reddit messages",
        )
    ]


def _collect_urgent_items(integration: str, snapshot: IntegrationSnapshot) -> list[UrgentItem]:
    return [
        *_gmail_items(snapshot),
        *_slack_items(snapshot),
        *_linear_items(snapshot),
        *_calendar_items(snapshot),
        *_github_items(snapshot),
        *_task_items(integration.lower(), snapshot),
        *_teams_items(snapshot),
        *_reddit_items(snapshot),
    ]


def register_urgency_custom_tools(composio: Composio) -> list[str]:
    """Register urgency aggregator tool as a Composio custom tool."""

    @composio.tools.custom_tool(toolkit="GAIA")
    def CUSTOM_URGENCY_AGGREGATOR(
        request: UrgencyAggregatorInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Aggregate urgency signals from multiple integration context snapshots.

        Takes outputs from multiple CUSTOM_GATHER_CONTEXT calls and returns a
        prioritized list of items that need immediate attention across all integrations.

        Args:
            request.snapshots: Dict of integration name -> context snapshot

        Returns:
            Dict with urgent_items list (sorted by priority) and summary counts
        """
        del execute_request, auth_credentials  # unused: framework-mandated custom-tool signature
        urgent_items: list[UrgentItem] = []
        for integration, snapshot in request.snapshots.items():
            urgent_items.extend(_collect_urgent_items(integration, snapshot))

        # Sort: high > medium > low, then by count descending
        urgent_items.sort(key=lambda item: (_PRIORITY_ORDER[item.priority], -item.count))

        high_count = sum(1 for i in urgent_items if i.priority == "high")
        medium_count = sum(1 for i in urgent_items if i.priority == "medium")
        low_count = sum(1 for i in urgent_items if i.priority == "low")

        return {
            "urgent_items": [
                item.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                    mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                    exclude_unset=True,
                )
                for item in urgent_items
            ],
            "total_urgent": len(urgent_items),
            "summary": {
                "high_priority": high_count,
                "medium_priority": medium_count,
                "low_priority": low_count,
            },
        }

    return ["GAIA_CUSTOM_URGENCY_AGGREGATOR"]
