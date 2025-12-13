"""
WebSocket event consumer for processing RabbitMQ messages in the main app.
"""

import json
from typing import Optional

from aio_pika import connect_robust
from aio_pika.abc import AbstractIncomingMessage

from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.core.websocket_manager import websocket_manager


class WebSocketEventConsumer:
    """Consumer for WebSocket broadcast events from RabbitMQ"""

    def __init__(self):
        self.connection = None
        self.channel = None
        self.queue = None
        self.consumer_tag = None

    async def start(self) -> None:
        """Start the WebSocket event consumer"""
        try:
            self.connection = await connect_robust(settings.RABBITMQ_URL, timeout=10)
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)

            # Declare the websocket-events queue
            self.queue = await self.channel.declare_queue(
                "websocket-events", durable=True
            )

            # Start consuming
            await self.queue.consume(self._handle_websocket_message)

            logger.info("WebSocket event consumer started on queue: websocket-events")

        except Exception as e:
            logger.error(f"Failed to start WebSocket event consumer: {e}")
            raise

    async def stop(self) -> None:
        """Stop the WebSocket event consumer"""
        try:
            if self.consumer_tag and self.queue:
                await self.queue.cancel(self.consumer_tag)

            if self.channel:
                await self.channel.close()

            if self.connection:
                await self.connection.close()

            logger.info("WebSocket event consumer stopped")

        except Exception as e:
            logger.error(f"Error stopping WebSocket event consumer: {e}")

    async def _handle_websocket_message(self, message: AbstractIncomingMessage) -> None:
        """Handle incoming WebSocket broadcast messages from RabbitMQ"""
        async with message.process():
            try:
                # Parse message data
                data = json.loads(message.body.decode())

                if data.get("type") != "websocket_broadcast":
                    logger.warning(
                        f"Received unknown WebSocket message type: {data.get('type')}"
                    )
                    return

                user_id = data.get("user_id")
                ws_message = data.get("message")

                if not user_id or not ws_message:
                    logger.error(
                        "Invalid WebSocket broadcast message: missing user_id or message"
                    )
                    return

                # Broadcast to WebSocket connections in the main app
                if user_id in websocket_manager.connections:
                    disconnected = set()
                    for websocket in websocket_manager.connections[user_id]:
                        try:
                            await websocket.send_json(ws_message)
                        except Exception as e:
                            logger.warning(
                                f"Failed to send WebSocket message to user {user_id}: {e}"
                            )
                            disconnected.add(websocket)

                    # Remove disconnected websockets
                    for ws in disconnected:
                        websocket_manager.connections[user_id].discard(ws)

                    logger.debug(f"Broadcasted WebSocket message to user {user_id}")
                else:
                    logger.debug(f"No WebSocket connections found for user {user_id}")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode WebSocket message JSON: {e}")
            except Exception as e:
                logger.error(f"Failed to process WebSocket message: {e}")


# Global instance
websocket_consumer: Optional[WebSocketEventConsumer] = None


async def start_websocket_consumer() -> None:
    """Start the global WebSocket event consumer"""
    global websocket_consumer
    if websocket_consumer is None:
        websocket_consumer = WebSocketEventConsumer()
        await websocket_consumer.start()


async def stop_websocket_consumer() -> None:
    """Stop the global WebSocket event consumer"""
    global websocket_consumer
    if websocket_consumer is not None:
        await websocket_consumer.stop()
        websocket_consumer = None
