"""Delivery events: where GAIA's own messages go, and the messages the outbox sent.

A message GAIA sends on its own (a fired reminder, an executor, workflow or tracked
todo result) goes to one place. The destination
types name that place and the rule that chose it, so routing is measurable on each
event.
"""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent

__all__ = [
    "DeliveryItemHeld",
    "DeliveryMessageSent",
    "ProactiveDestinationBasis",
    "ProactiveDestinationKind",
]

#: A chat app (Telegram, WhatsApp, ...) or the GAIA app itself.
ProactiveDestinationKind = Literal["chat_app", "in_app"]

#: Why: the user was active there, it led their chat-app order, the answer went back to the
#: direct message that asked, the producer named the chat app, they were active in the GAIA app,
#: or no chat app was usable.
ProactiveDestinationBasis = Literal[
    "recent_activity", "priority", "owner_chat", "requested_channel", "active_in_app", "no_chat_app"
]


class DeliveryMessageSent(ServerEvent):
    """The outbox sent one message to a user: a chat app took it, or it was recorded in the GAIA app."""

    event: ClassVar[str] = "delivery:message_sent"
    previous_names: ClassVar[tuple[str, ...]] = (
        "reminder:completed",
        "workflow:result_delivered",
        "todos:run_result_delivered",
        "chat:background_update_resolved",
    )
    budget_per_user_day: ClassVar[int] = 500

    producer: Literal[
        "executor", "workflow", "todo", "reminder", "browser", "artifact", "account", "approval"
    ]
    subject_kind: Literal[
        "ask", "workflow_run", "todo_run", "reminder", "browser_job", "account", "approval"
    ]
    mode: Literal["answer", "unsolicited", "interrupt"]
    destination: ProactiveDestinationKind
    destination_basis: ProactiveDestinationBasis
    items_count: int
    max_class: Literal["background", "routine", "timely", "interrupt"]
    degraded: bool


class DeliveryItemHeld(ServerEvent):
    """The outbox held an item to tell the user later: why, and how urgent it was."""

    event: ClassVar[str] = "delivery:item_held"
    budget_per_user_day: ClassVar[int] = 500

    reason: Literal["quiet_hours", "dnd", "not_before", "checkin", "gap", "wait_for_run"]
    max_class: Literal["background", "routine", "timely", "interrupt"]
