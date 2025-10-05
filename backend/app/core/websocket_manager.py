import json
from typing import Any, ClassVar, Dict, Set, TypeVar, cast

from app.config.loggers import common_logger as logger
from app.db.rabbitmq import get_rabbitmq_publisher
from app.utils.worker_detection import is_main_app
from fastapi import WebSocket

T = TypeVar("T", bound="WebSocketManager")


class WebSocketManager:
    """Manages WebSocket connections for real-time notifications"""

    _instance: ClassVar[Any] = None

    def __new__(cls: type[T]) -> T:
        if cls._instance is None:
            cls._instance = super(WebSocketManager, cls).__new__(cls)
            # Initialize the instance in __new__ for singleton pattern
            cls._instance.initialized = False
            logger.info("Created new WebSocketManager instance")
        return cast(T, cls._instance)

    def __init__(self) -> None:
        # Only initialize once
        if not hasattr(self, "initialized") or not self.initialized:
            self.connections: Dict[str, Set[WebSocket]] = {}
            self.initialized: bool = True

    def add_connection(self, user_id: str, websocket: WebSocket) -> None:
        """Add a WebSocket connection for a user"""
        if user_id not in self.connections:
            self.connections[user_id] = set()
        self.connections[user_id].add(websocket)
        logger.info(f"Added WebSocket connection for user {user_id}")

    def remove_connection(self, user_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection for a user"""
        if user_id in self.connections:
            self.connections[user_id].discard(websocket)
            if not self.connections[user_id]:
                del self.connections[user_id]
        logger.info(f"Removed WebSocket connection for user {user_id}")

    async def broadcast_to_user(self, user_id: str, message: Dict[str, Any]) -> None:
        """Broadcast message to all connections for a user"""

        # If we don't have websocket pool (not main app), publish to RabbitMQ
        if not is_main_app():
            await self._publish_to_rabbitmq(user_id, message)
            return

        if user_id not in self.connections:
            return

        disconnected = set()
        for websocket in self.connections[user_id]:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.add(websocket)

        # Remove disconnected websockets
        for ws in disconnected:
            self.connections[user_id].discard(ws)

    async def _publish_to_rabbitmq(self, user_id: str, message: Dict[str, Any]) -> None:
        """Publish WebSocket message to RabbitMQ for main app to broadcast."""
        try:
            publisher = await get_rabbitmq_publisher()

            # Create message for WebSocket broadcasting
            rabbitmq_message = {
                "type": "websocket_broadcast",
                "user_id": user_id,
                "message": message,
            }

            message_body = json.dumps(rabbitmq_message).encode("utf-8")
            # Publisher now handles connection health automatically
            await publisher.publish("websocket-events", message_body)

            logger.debug(f"Published WebSocket message for user {user_id} to RabbitMQ")

        except Exception as e:
            logger.error(
                f"Failed to publish WebSocket message to RabbitMQ: {e}", exc_info=True
            )


# Create a singleton instance of WebSocketManager
websocket_manager = WebSocketManager()


def get_websocket_manager() -> WebSocketManager:
    """Get the singleton instance of WebSocketManager"""
    return websocket_manager
