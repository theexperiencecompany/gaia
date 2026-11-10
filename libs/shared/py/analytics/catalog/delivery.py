"""Where a proactive message went: the property kinds every proactive delivery event shares.

A message GAIA sends on its own (a fired reminder, a workflow result, a tracked
todo's result, an unnamed agent notification) goes to one place. These name
that place and the rule that chose it, so routing is measurable on each event.
"""

from typing import Literal, TypedDict

#: A chat app (Telegram, WhatsApp, ...) or the GAIA app itself.
ProactiveDestinationKind = Literal["chat_app", "in_app"]

#: Why: the user was active there, it led their chat-app order, they were active in the
#: GAIA app, or no chat app was usable.
ProactiveDestinationBasis = Literal["recent_activity", "priority", "active_in_app", "no_chat_app"]


class ProactiveDestination(TypedDict):
    """The destination properties of a delivery event; both None when the destination was never resolved."""

    destination: ProactiveDestinationKind | None
    destination_basis: ProactiveDestinationBasis | None


__all__ = ["ProactiveDestination", "ProactiveDestinationBasis", "ProactiveDestinationKind"]
