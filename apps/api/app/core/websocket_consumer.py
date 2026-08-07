"""
WebSocket event consumer for processing RabbitMQ messages in the main app.
"""

import json

from aio_pika import connect_robust
from aio_pika.abc import (
    AbstractChannel,
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from shared.py.wide_events import log, log_context


class WebSocketEventConsumer:
    """Consumer for WebSocket broadcast events from RabbitMQ"""

    def __init__(self) -> None:
        self.connection: AbstractRobustConnection | None = None
        self.channel: AbstractChannel | None = None
        self.queue: AbstractQueue | None = None
        self.consumer_tag: str | None = None

    async def start(self) -> None:
        """Start the WebSocket event consumer"""
        try:
            self.connection = await connect_robust(settings.RABBITMQ_URL, timeout=10)
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)

            # Declare the websocket-events queue
            self.queue = await self.channel.declare_queue("websocket-events", durable=True)

            # Start consuming
            await self.queue.consume(self._handle_websocket_message)

            log.info(
                f"{LogTag.STARTUP} WebSocket event consumer started on queue: websocket-events"
            )

        except Exception as e:
            log.error(
                f"{LogTag.STARTUP} Failed to start WebSocket event consumer",
                error=str(e),
                error_type=type(e).__name__,
            )
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

            log.info(f"{LogTag.STARTUP} WebSocket event consumer stopped")

        except Exception as e:
            log.error(
                f"{LogTag.STARTUP} Error stopping WebSocket event consumer",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _handle_websocket_message(self, message: AbstractIncomingMessage) -> None:
        """Handle one server→client push off the RabbitMQ queue, as its own wide event.

        This consumer carries every broadcast the workers hand to the main app,
        and runs with no middleware behind it — without a boundary per message
        the delivery outcome and all four error paths below are discarded.
        """
        # No `operation=` kwarg: log_context's own first parameter is named
        # `operation`, so passing one collides. The boundary's `task` field
        # already carries the operation name.
        async with log_context("websocket_event"):
            async with message.process():
                try:
                    # Parse message data
                    data = json.loads(message.body.decode())

                    if data.get("type") != "websocket_broadcast":
                        log.warning(
                            f"{LogTag.STARTUP} Received unknown WebSocket message type",
                            message_type=data.get("type"),
                        )
                        return

                    user_id = data.get("user_id")
                    ws_message = data.get("message")

                    if user_id:
                        log.set(user={"id": user_id})

                    if not user_id or not ws_message:
                        log.error(
                            f"{LogTag.STARTUP} Invalid WebSocket broadcast message: missing user_id or message"
                        )
                        return

                    # Broadcast to WebSocket connections in the main app
                    if user_id in websocket_manager.connections:
                        disconnected = set()
                        for websocket in websocket_manager.connections[user_id]:
                            try:
                                await websocket.send_json(ws_message)
                            except Exception as e:
                                log.warning(
                                    f"{LogTag.STARTUP} Failed to send WebSocket message to user",
                                    user_id=user_id,
                                    error=str(e),
                                    error_type=type(e).__name__,
                                )
                                disconnected.add(websocket)

                        # Remove disconnected websockets
                        for ws in disconnected:
                            websocket_manager.connections[user_id].discard(ws)

                        # Sockets that survived the fan-out; each failure is
                        # already an entry in the event's warnings[].
                        log.set(result_count=len(websocket_manager.connections[user_id]))
                        log.debug(
                            f"{LogTag.STARTUP} Broadcasted WebSocket message to user",
                            user_id=user_id,
                        )
                    else:
                        log.set(result_count=0)
                        log.debug(
                            f"{LogTag.STARTUP} No WebSocket connections found for user",
                            user_id=user_id,
                        )

                except json.JSONDecodeError as e:
                    log.error(
                        f"{LogTag.STARTUP} Failed to decode WebSocket message JSON",
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                except Exception as e:
                    log.error(
                        f"{LogTag.STARTUP} Failed to process WebSocket message",
                        error=str(e),
                        error_type=type(e).__name__,
                    )


# Global instance
websocket_consumer: WebSocketEventConsumer | None = None


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
