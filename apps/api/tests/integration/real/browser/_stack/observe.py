"""What a Telegram user of the browser stack would receive: the outbound queue, read as transcripts.

The API and the worker publish every bot message to outbound.telegram on
the stack's RabbitMQ vhost, as in production. The real bot is not running; this
reads the queue in its place, without competing for it: one relay at a time
holds an exclusive consumer and copies each message to a per-chat transcript
queue, in queue order. A second stack on the same vhost (another xdist worker)
waits for the exclusive consumer and takes over when the holder goes, so
neither ever steals the other's messages, and each stack reads only the chats
it registered. A message for a chat nobody registered is dropped.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import re
import time
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage, AbstractRobustConnection
import aiormq.exceptions

from app.constants.chat import ConversationSource
from app.constants.outbound import OUTBOUND_QUEUES, work_queue_arguments
from tests.integration.real.browser._stack.progress import Progress

_OUTBOUND = OUTBOUND_QUEUES[ConversationSource.TELEGRAM]
_TRANSCRIPT_PREFIX = "browser-stack.transcript."
#: How long the relay waits before asking again for a consumer another stack holds.
_RELAY_RETRY_SECONDS = 0.5
_POLL_SECONDS = 0.2
#: How long connecting to the broker may take.
_CONNECT_SECONDS = 30.0
#: How often a relay kept off the outbound queue says so.
_RELAY_REPORT_SECONDS = 30.0


@dataclass(frozen=True)
class Delivery:
    """One message the bot would have sent, as the envelope carried it."""

    destination_id: str
    is_channel: bool
    text: str
    photo_url: str | None
    caption: str | None
    at: float

    @property
    def said(self) -> str:
        """Everything the user reads in it: the text, or a photo's caption."""
        return self.text or (self.caption or "")


@dataclass
class Transcript:
    """Everything delivered to one chat, oldest first."""

    destination_id: str
    deliveries: list[Delivery] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [d.text for d in self.deliveries if d.text]

    @property
    def photos(self) -> list[Delivery]:
        return [d for d in self.deliveries if d.photo_url]

    def matching(self, pattern: str) -> list[Delivery]:
        return [d for d in self.deliveries if re.search(pattern, d.said, re.IGNORECASE)]


def _delivery(envelope: dict[str, Any]) -> Delivery:
    attachment = envelope.get("attachment") or {}
    parts = envelope.get("text_parts") or []
    return Delivery(
        destination_id=str(envelope["destination_id"]),
        is_channel=bool(envelope.get("is_channel")),
        text=envelope.get("text") or "\n".join(parts),
        photo_url=attachment.get("url"),
        caption=attachment.get("caption"),
        at=time.monotonic(),
    )


class OutboundObserver:
    """Reads the stack's outbound Telegram messages into one transcript per registered chat."""

    def __init__(self, rabbitmq_url: str, progress: Progress) -> None:
        self._url = rabbitmq_url
        self._progress = progress
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._relay: asyncio.Task[None] | None = None
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
        if self._relay is not None:
            self._relay.cancel()
            await asyncio.gather(self._relay, return_exceptions=True)
        if self._connection is not None:
            await self._connection.close()

    async def drained(self) -> bool:
        """Whether every message published so far has reached its transcript."""
        if self._channel is None:
            raise RuntimeError("the observer is not started")
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

    async def watch(self, destination_id: str) -> Transcript:
        """Start collecting what is sent to one chat; call before anything is sent there."""
        if self._channel is None:
            raise RuntimeError("the observer is not started")
        transcript = self.transcripts.setdefault(destination_id, Transcript(destination_id))
        queue = await self._channel.declare_queue(
            f"{_TRANSCRIPT_PREFIX}{destination_id}", exclusive=True, auto_delete=True
        )

        async def collect(message: AbstractIncomingMessage) -> None:
            async with message.process():
                transcript.deliveries.append(_delivery(json.loads(message.body)))

        await queue.consume(collect)
        return transcript

    async def _relay_forever(self) -> None:
        if self._connection is None:
            raise RuntimeError("the observer is not started")
        refused_since: float | None = None
        while True:
            channel = await self._connection.channel()
            try:
                queue = await channel.declare_queue(
                    _OUTBOUND, durable=True, arguments=work_queue_arguments(_OUTBOUND)
                )
                async with queue.iterator(exclusive=True) as messages:
                    refused_since = None
                    async for message in messages:
                        await self._copy(channel, message)
            except (
                aiormq.exceptions.ChannelAccessRefused,
                aiormq.exceptions.ChannelLockedResource,
            ):
                # Another stack's relay holds the queue; take over once it lets go. A holder
                # that never does (a bot consuming this vhost) is said, not waited on in silence.
                now = time.monotonic()
                refused_since = refused_since or now
                if now - refused_since >= _RELAY_REPORT_SECONDS:
                    self._progress.say(
                        f"{_OUTBOUND} has been held by another consumer for "
                        f"{now - refused_since:.0f}s: another stack's relay, or a bot on this vhost"
                    )
                    refused_since = now
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


async def wait_for(transcript: Transcript, pattern: str, *, timeout: float) -> Delivery:
    """Return the first delivery to transcript matching pattern, polling until timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = transcript.matching(pattern)
        if found:
            return found[0]
        await asyncio.sleep(_POLL_SECONDS)
    raise AssertionError(
        f"nothing matching {pattern!r} reached {transcript.destination_id} in {timeout}s: "
        f"{[d.said[:120] for d in transcript.deliveries]}"
    )
