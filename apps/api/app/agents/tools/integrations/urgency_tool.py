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

            # Gmail: unread count
            if "inbox" in snapshot:
                unread = snapshot["inbox"].get("unread_count", 0)
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

            # Slack: unread mentions / channels
            if "unread_channels" in snapshot:
                channels = snapshot["unread_channels"]
                if channels:
                    urgent_items.append(
                        {
                            "integration": "slack",
                            "type": "unread_channels",
                            "count": len(channels),
                            "priority": "high",
                            "description": f"{len(channels)} Slack channels with unread messages",
                            "details": [c.get("name") for c in channels[:5]],
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

            # Google Calendar: upcoming events in next hour
            if "upcoming_events" in snapshot:
                events = snapshot["upcoming_events"]
                if events:
                    urgent_items.append(
                        {
                            "integration": "googlecalendar",
                            "type": "upcoming_events",
                            "count": len(events),
                            "priority": "medium",
                            "description": f"{len(events)} upcoming calendar events",
                            "details": [e.get("summary") for e in events[:3]],
                        }
                    )

            # GitHub: notifications
            if "unread_notification_count" in snapshot:
                notif_count = snapshot["unread_notification_count"]
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
