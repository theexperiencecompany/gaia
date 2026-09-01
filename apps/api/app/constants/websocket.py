"""Constants for the user-facing WebSocket fan-out.

A user's browser/mobile sockets land on whichever API replica the load balancer
picked, and the same user can hold sockets on several replicas at once. Anything
that pushes to those sockets (an API request handler, an ARQ worker) therefore
has to reach *every* replica, not one of them.
"""

from typing import Final

# Pub/sub, deliberately not a work queue: every replica subscribes and writes to
# its own sockets. A queue would hand each broadcast to one competing consumer,
# so a user connected to any other replica would silently never receive it.
WEBSOCKET_BROADCAST_CHANNEL: Final[str] = "websocket:broadcast"

# How long the per-pod listener waits before re-subscribing after Redis drops it.
WEBSOCKET_LISTENER_RESUBSCRIBE_SECONDS: Final[float] = 5.0
