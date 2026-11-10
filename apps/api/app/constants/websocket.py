"""Constants for the user-facing WebSocket fan-out.

A user's browser/mobile sockets land on whichever API replica the load balancer
picked, and the same user can hold sockets on several replicas at once. Anything
that pushes to those sockets (an API request handler, an ARQ worker) therefore
has to reach *every* replica, not one of them.
"""

from enum import StrEnum
from typing import Final

# Pub/sub, deliberately not a work queue: every replica subscribes and writes to
# its own sockets. A queue would hand each broadcast to one competing consumer,
# so a user connected to any other replica would silently never receive it.
WEBSOCKET_BROADCAST_CHANNEL: Final[str] = "websocket:broadcast"

# How long the per-pod listener waits before re-subscribing after Redis drops it.
WEBSOCKET_LISTENER_RESUBSCRIBE_SECONDS: Final[float] = 5.0

# Pause before the one retry of a failed per-user broadcast.
WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS: Final[float] = 0.5

# The one WebSocket event that carries words to the user. State-sync events
# (integration status, executor stream started/cancelled, approval decided,
# onboarding stage) keep their own names and never travel under this one.
WS_EVENT_OUTBOX_MESSAGE: Final[str] = "outbox.message"


class OutboxMessageKind(StrEnum):
    """What an outbox.message frame carries, named by its kind field."""

    CONVERSATION_MESSAGE = "conversation_message"
    NOTIFICATION = "notification"
