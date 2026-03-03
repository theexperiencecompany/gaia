"""Cross-integration urgency aggregator tool.

Aggregates urgency signals across multiple integration context snapshots
into a single prioritized list of items needing attention.
"""

from typing import Any, Dict, List

from composio import Composio
from pydantic import BaseModel, Field


class UrgencyAggregatorInput(BaseModel):
    """Input for the urgency aggregator — a dict of integration snapshots."""

    snapshots: Dict[str, Any] = Field(
        ...,
        description=(
            "Dict mapping integration name to its CUSTOM_GATHER_CONTEXT output. "
            "Example: {'gmail': {...}, 'slack': {...}, 'linear': {...}}"
        ),
    )


def register_urgency_custom_tools(composio: Composio) -> List[str]:
    """Register urgency aggregator tool as a Composio custom tool."""

    @composio.tools.custom_tool(toolkit="GAIA")
    def CUSTOM_URGENCY_AGGREGATOR(
        request: UrgencyAggregatorInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Aggregate urgency signals from multiple integration context snapshots.

        Takes outputs from multiple CUSTOM_GATHER_CONTEXT calls and returns a
        prioritized list of items that need immediate attention across all integrations.

        Args:
            request.snapshots: Dict of integration name -> context snapshot dict

        Returns:
            Dict with urgent_items list (sorted by priority) and summary counts
        """
        urgent_items: List[Dict[str, Any]] = []

        for integration, snapshot in request.snapshots.items():
            if not isinstance(snapshot, dict):
                continue

            integration_lower = integration.lower()

            # Gmail: unread count (data is flat — inbox_unread_count at top level)
            if "inbox_unread_count" in snapshot or "unread_count" in snapshot:
                unread = snapshot.get("inbox_unread_count") or snapshot.get(
                    "unread_count", 0
                )
                if unread > 0:
                    urgent_items.append(
                        {
                            "integration": "gmail",
                            "type": "unread_emails",
                            "count": unread,
                            "priority": "high" if unread > 20 else "medium",
                            "description": f"{unread} unread emails in inbox",
                        }
                    )

            # Slack: unread mentions / messages
            if "mentions" in snapshot or "unread_count" in snapshot:
                mentions_list = snapshot.get("mentions", [])
                unread_count = snapshot.get("unread_count", 0)
                if mentions_list or unread_count:
                    count = len(mentions_list) if mentions_list else unread_count
                    urgent_items.append(
                        {
                            "integration": "slack",
                            "type": "unread_messages",
                            "count": count,
                            "priority": "high",
                            "description": (
                                f"{len(mentions_list)} Slack @mentions"
                                if mentions_list
                                else f"{unread_count} unread Slack messages"
                            ),
                            "details": [
                                m.get("text", "")[:80] for m in mentions_list[:3]
                            ],
                        }
                    )

            # Linear: overdue issues
            if "overdue_issues" in snapshot:
                overdue = snapshot["overdue_issues"]
                if overdue:
                    urgent_items.append(
                        {
                            "integration": "linear",
                            "type": "overdue_issues",
                            "count": len(overdue),
                            "priority": "high",
                            "description": f"{len(overdue)} overdue Linear issues",
                            "details": [i.get("title") for i in overdue[:3]],
                        }
                    )

            # Google Calendar: today's events
            if "events" in snapshot or "next_event" in snapshot:
                events = snapshot.get("events", [])
                next_event = snapshot.get("next_event")
                if events or next_event:
                    event_list = events or ([next_event] if next_event else [])
                    urgent_items.append(
                        {
                            "integration": "googlecalendar",
                            "type": "upcoming_events",
                            "count": len(event_list),
                            "priority": "medium",
                            "description": f"{len(event_list)} calendar events today",
                            "details": [
                                e.get("summary", e.get("title", ""))
                                for e in event_list[:3]
                            ],
                        }
                    )

            # GitHub: notifications and review requests
            if "notifications" in snapshot or "review_requests" in snapshot:
                notifications_list = snapshot.get("notifications", [])
                review_requests = snapshot.get("review_requests", [])
                notif_count = len(notifications_list)
                review_count = len(review_requests)
                if notif_count > 0:
                    urgent_items.append(
                        {
                            "integration": "github",
                            "type": "unread_notifications",
                            "count": notif_count,
                            "priority": "medium",
                            "description": f"{notif_count} unread GitHub notifications",
                        }
                    )
                if review_count > 0:
                    urgent_items.append(
                        {
                            "integration": "github",
                            "type": "review_requests",
                            "count": review_count,
                            "priority": "high",
                            "description": f"{review_count} GitHub PRs awaiting your review",
                            "details": [
                                pr.get("title", "") for pr in review_requests[:3]
                            ],
                        }
                    )

            # Asana / Todoist / ClickUp: overdue tasks
            overdue_tasks = snapshot.get("overdue_tasks", [])
            if not overdue_tasks:
                # Try urgent_tasks for Google Tasks
                overdue_tasks = [
                    t for t in snapshot.get("urgent_tasks", []) if t.get("overdue")
                ]
            if overdue_tasks:
                urgent_items.append(
                    {
                        "integration": integration_lower,
                        "type": "overdue_tasks",
                        "count": len(overdue_tasks),
                        "priority": "high",
                        "description": (
                            f"{len(overdue_tasks)} overdue tasks in {integration_lower}"
                        ),
                        "details": [
                            t.get("name") or t.get("title") for t in overdue_tasks[:3]
                        ],
                    }
                )

            # Teams: unread chats
            if "unread_chat_count" in snapshot:
                unread_chats = snapshot["unread_chat_count"]
                if unread_chats > 0:
                    urgent_items.append(
                        {
                            "integration": "microsoft_teams",
                            "type": "unread_chats",
                            "count": unread_chats,
                            "priority": "medium",
                            "description": f"{unread_chats} unread Microsoft Teams chats",
                        }
                    )

            # Reddit: unread messages
            if "unread_message_count" in snapshot:
                unread_msgs = snapshot["unread_message_count"]
                if unread_msgs > 0:
                    urgent_items.append(
                        {
                            "integration": "reddit",
                            "type": "unread_messages",
                            "count": unread_msgs,
                            "priority": "low",
                            "description": f"{unread_msgs} unread Reddit messages",
                        }
                    )

        # Sort: high > medium > low, then by count descending
        priority_order = {"high": 0, "medium": 1, "low": 2}
        urgent_items.sort(
            key=lambda x: (
                priority_order.get(x["priority"], 3),
                -x.get("count", 0),
            )
        )

        high_count = sum(1 for i in urgent_items if i["priority"] == "high")
        medium_count = sum(1 for i in urgent_items if i["priority"] == "medium")
        low_count = sum(1 for i in urgent_items if i["priority"] == "low")

        return {
            "urgent_items": urgent_items,
            "total_urgent": len(urgent_items),
            "summary": {
                "high_priority": high_count,
                "medium_priority": medium_count,
                "low_priority": low_count,
            },
        }

    return ["GAIA_CUSTOM_URGENCY_AGGREGATOR"]
