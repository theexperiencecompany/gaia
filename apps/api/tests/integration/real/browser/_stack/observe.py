"""What a Telegram user of the browser stack would receive: the outbound queue and the conversations it wakes, as transcripts.

The API and the worker publish every bot message to outbound.telegram on
the stack's RabbitMQ vhost, as in production. The real bot is not running; this
reads the queue in its place, without competing for it: one relay at a time
holds an exclusive consumer and copies each message to a per-chat transcript
queue, in queue order. A second stack on the same vhost (another xdist worker)
waits for the exclusive consumer and takes over when the holder goes, so
neither ever steals the other's messages, and each stack reads only the chats
it registered. A message for a chat nobody registered is dropped. A wake on
the queue carries no content: its conversation is followed as the bot does (chat_follow).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage, AbstractRobustConnection
import aiormq.exceptions

from app.constants.chat import ConversationSource
from app.constants.outbound import OUTBOUND_QUEUES, work_queue_arguments
from app.models.conversation_send_models import ActiveBotConversation
from tests.integration.real.browser._stack.chat_follow import BotHeaders, ChatFollow
from tests.integration.real.browser._stack.progress import Progress
from tests.integration.real.browser._stack.transcript import Delivery, Transcript

_OUTBOUND = OUTBOUND_QUEUES[ConversationSource.TELEGRAM]
_TRANSCRIPT_PREFIX = "browser-stack.transcript."
#: How long the relay waits before asking again for a consumer another stack holds.
_RELAY_RETRY_SECONDS = 0.5
#: How long connecting to the broker may take.
_CONNECT_SECONDS = 30.0


def _delivery(envelope: dict[str, Any]) -> Delivery | None:
    """Return the message an envelope carries itself; None for a wake, which carries none."""
    attachment = envelope.get("attachment") or {}
    parts = envelope.get("text_parts") or []
    text = envelope.get("text") or "\n".join(parts)
    if not text and not attachment:
        return None
    return Delivery(
        destination_id=str(envelope["destination_id"]),
        is_channel=bool(envelope.get("is_channel")),
        text=text,
        photo_url=attachment.get("url"),
        caption=attachment.get("caption"),
        at=time.monotonic(),
    )


class OutboundObserver:
    """Reads the stack's outbound Telegram messages, and the conversations they wake, into one transcript per chat."""

    def __init__(
        self, rabbitmq_url: str, progress: Progress, api_url: str, bot_headers: BotHeaders
    ) -> None:
        self._url = rabbitmq_url
        self._progress = progress
        self._api_url = api_url
        self._bot_headers = bot_headers
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._relay: asyncio.Task[None] | None = None
        self._chats: dict[str, ChatFollow] = {}
        self._follows: dict[str, asyncio.Task[None]] = {}
        self.transcripts: dict[str, Transcript] = {}

    async def start(self) -> None:
        async with asyncio.timeout(_CONNECT_SECONDS):
            self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        # Declared as the API declares it, so the relay can consume before the API published anything.
        await self._channel.declare_queue(
            _OUTBOUND, durable=True, arguments=work_queue_arguments(_OUTBOUND)
        )
        self._relay = asyncio.create_task(self._relay_forever())

    async def stop(self) -> None:
        tasks = [*self._follows.values(), *([self._relay] if self._relay is not None else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._connection is not None:
            await self._connection.close()

    async def drained(self) -> bool:
        """Whether every message published so far has reached its transcript, and every woken conversation is idle."""
        if self._channel is None:
            raise RuntimeError("the observer is not started")
        for task in self._follows.values():
            if not task.done():
                return False
            task.result()
        outbound = await self._channel.declare_queue(_OUTBOUND, passive=True)
        if outbound.declaration_result.message_count:
            return False
        for destination in self.transcripts:
            queue = await self._channel.declare_queue(
                f"{_TRANSCRIPT_PREFIX}{destination}", passive=True
            )
            if queue.declaration_result.message_count:
                return False
        return True

    def follow(self, conversation: ActiveBotConversation, *, expect: int | None = None) -> None:
        """Follow a conversation from its cursor until idle, joining the follow already running for it."""
        chat = self._chats.get(conversation.conversation_id)
        if chat is None:
            chat = self._chats[conversation.conversation_id] = ChatFollow(conversation, self._send)
        if expect is not None:
            chat.expected.add(expect)
        running = self._follows.get(conversation.conversation_id)
        if running is not None and not running.done():
            return
        if running is not None:
            running.result()
        chat.conversation = conversation
        task = asyncio.create_task(chat.follow(self._api_url, self._bot_headers))
        task.add_done_callback(self._say_failure)
        self._follows[conversation.conversation_id] = task

    def _say_failure(self, task: asyncio.Task[None]) -> None:
        """Say a follow's failure as it happens; drained raises it, but a scenario may be waiting on a line."""
        if not task.cancelled() and task.exception() is not None:
            self._progress.say(f"a conversation follow failed: {task.exception()!r}")

    def _send(self, delivery: Delivery) -> None:
        transcript = self.transcripts.get(delivery.destination_id)
        if transcript is not None:
            transcript.deliveries.append(delivery)

    async def watch(self, destination_id: str) -> Transcript:
        """Start collecting what is sent to one chat; call before anything is sent there."""
        if self._channel is None:
            raise RuntimeError("the observer is not started")
        transcript = self.transcripts.setdefault(destination_id, Transcript(destination_id))
        transcript_queue = f"{_TRANSCRIPT_PREFIX}{destination_id}"
        queue = await self._channel.declare_queue(
            transcript_queue, exclusive=True, auto_delete=True
        )

        async def collect(message: AbstractIncomingMessage) -> None:
            async with message.process():
                envelope = json.loads(message.body)
                if envelope.get("follow") is not None:
                    self.follow(ActiveBotConversation.model_validate(envelope["follow"]))
                delivery = _delivery(envelope)
                if delivery is not None:
                    transcript.deliveries.append(delivery)

        # Named, not aiormq's default: that one is drawn from `random`, which pytest-randomly
        # reseeds identically for a test's rerun, so the rerun's tag collided with the failed
        # attempt's consumer still on this module-long channel.
        await queue.consume(collect, consumer_tag=transcript_queue)
        return transcript

    async def _relay_forever(self) -> None:
        if self._connection is None:
            raise RuntimeError("the observer is not started")
        relaying: bool | None = None
        while True:
            channel = await self._connection.channel()
            try:
                queue = await channel.declare_queue(
                    _OUTBOUND, durable=True, arguments=work_queue_arguments(_OUTBOUND)
                )
                async with queue.iterator(exclusive=True) as messages:
                    if relaying is not True:
                        self._progress.say(f"this stack relays {_OUTBOUND}")
                    relaying = True
                    async for message in messages:
                        await self._copy(channel, message)
            except (
                aiormq.exceptions.ChannelAccessRefused,
                aiormq.exceptions.ChannelLockedResource,
            ):
                # Another consumer holds the queue: another stack's relay, which copies this
                # stack's chats too, or a bot on this vhost, which would starve them. Said once.
                if relaying is not False:
                    self._progress.say(
                        f"another consumer relays {_OUTBOUND} (another stack in this run "
                        "copies these chats too; a bot on this vhost would swallow them)"
                    )
                relaying = False
                await asyncio.sleep(_RELAY_RETRY_SECONDS)
            finally:
                if not channel.is_closed:
                    await channel.close()

    @staticmethod
    async def _copy(channel: AbstractChannel, message: AbstractIncomingMessage) -> None:
        async with message.process():
            destination = json.loads(message.body)["destination_id"]
            await channel.default_exchange.publish(
                aio_pika.Message(body=message.body),
                routing_key=f"{_TRANSCRIPT_PREFIX}{destination}",
            )
