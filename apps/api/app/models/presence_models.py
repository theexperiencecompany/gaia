"""Where the user is: when they last wrote on each surface.

A leaf, importing nothing from the app, so ``app.models.agent_config`` can carry
a snapshot on the run configurable without losing its own leaf status.
"""

from typing_extensions import TypedDict


class PresenceSnapshot(TypedDict):
    """The user's last inbound message per surface (ConversationSource value to epoch seconds), as of captured_at."""

    captured_at: int
    last_seen: dict[str, int]
