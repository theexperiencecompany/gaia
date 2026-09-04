import json
from typing import Any, ClassVar, TypeVar, cast

from fastapi import WebSocket

from app.constants.log_tags import LogTag
from app.constants.websocket import WEBSOCKET_BROADCAST_CHANNEL
from app.db.redis import redis_cache
from shared.py.wide_events import log

T = TypeVar("T", bound="WebSocketManager")


class WebSocketBroadcastError(RuntimeError):
    """A broadcast could not be published to the fan-out channel."""


class WebSocketManager:
    """The user WebSockets *this* process holds, plus the publisher that reaches the rest.

    Sending is never a direct write. ``broadcast_to_user`` only publishes to
    ``WEBSOCKET_BROADCAST_CHANNEL``; every replica's
    ``websocket_broadcast_listener`` picks the message up and calls
    ``deliver_local`` on its own sockets. That holds for the publishing replica
    too — it delivers through its own subscription like any other.

    Both halves of that are load-bearing. Publishing (rather than writing
    locally) is what lets a broadcast raised on replica A or in an ARQ worker
    reach a user whose socket lives on replica B. *Only* publishing is what
    keeps the publishing replica from delivering the same message twice, once
    directly and once off its own subscription.
    """

    _instance: ClassVar["WebSocketManager | None"] = None

    def __new__(cls: type[T]) -> T:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize the instance in __new__ for singleton pattern
            cls._instance.initialized = False
            log.info(f"{LogTag.STARTUP} Created new WebSocketManager instance")
        return cast(T, cls._instance)

    def __init__(self) -> None:
        # Only initialize once
        if not hasattr(self, "initialized") or not self.initialized:
            self.connections: dict[str, set[WebSocket]] = {}
            self.initialized: bool = True

    def add_connection(self, user_id: str, websocket: WebSocket) -> None:
        """Add a WebSocket connection for a user"""
        if user_id not in self.connections:
            self.connections[user_id] = set()
        self.connections[user_id].add(websocket)
        log.set(websocket={"user_id": user_id, "connection_id": id(websocket)})
        log.info(f"{LogTag.STARTUP} Added WebSocket connection for user", user_id=user_id)

    def remove_connection(self, user_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection for a user"""
        if user_id in self.connections:
            self.connections[user_id].discard(websocket)
            if not self.connections[user_id]:
                del self.connections[user_id]
        log.set(websocket={"user_id": user_id, "connection_id": id(websocket)})
        log.info(f"{LogTag.STARTUP} Removed WebSocket connection for user", user_id=user_id)

    async def broadcast_to_user(self, user_id: str, message: dict[str, Any]) -> None:
        """Publish a message to every replica holding one of this user's sockets.

        Callable from anywhere — request handlers, ARQ workers, schedulers. It
        does not write to this process's sockets; the listener does that.
        """
        client = redis_cache.redis
        if client is None:
            raise WebSocketBroadcastError(
                "Redis is not configured; WebSocket broadcasts cannot be delivered"
            )
        await client.publish(
            WEBSOCKET_BROADCAST_CHANNEL,
            json.dumps({"user_id": user_id, "message": message}),
        )

    async def deliver_local(self, user_id: str, message: dict[str, Any]) -> int:
        """Write a broadcast to this process's sockets; returns how many survived.

        Sockets that fail the write are already gone (the peer dropped without a
        close frame), so they are pruned rather than retried.
        """
        sockets = self.connections.get(user_id)
        if not sockets:
            return 0
        disconnected: set[WebSocket] = set()
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception as e:
                log.warning(
                    f"{LogTag.STARTUP} Failed to send to WebSocket",
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )
                disconnected.add(websocket)
        for ws in disconnected:
            sockets.discard(ws)
        if not sockets:
            del self.connections[user_id]
        return len(sockets)


# Create a singleton instance of WebSocketManager
websocket_manager = WebSocketManager()


def get_websocket_manager() -> WebSocketManager:
    """Get the singleton instance of WebSocketManager"""
    return websocket_manager
