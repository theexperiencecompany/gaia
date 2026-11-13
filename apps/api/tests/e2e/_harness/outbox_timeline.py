"""A timeline of events driven through the real outbox, asserted on the ledger it writes.

Real: intake, policy, watching (presence), router, compose's validation and degrade, deliver's state machine, the
two outbox repositories (on real Mongo, with the production indexes), the comms thread lock
(on fakeredis), presence (fakeredis, read through the clock seam).
Doubled: the clock, the ARQ queue (in memory, keyed on the instant a job is due), the Judge
(scripted: nothing remarkable unless a test says otherwise), the compose model (scripted), the comms thread (an in-memory graph), the speech transports (capture
sinks), and the user, conversation and bot-session reads (a World).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from arq import Retry
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio.lock import Lock

from app.constants.cache import COMMS_THREAD_LOCK_PREFIX
from app.constants.outbox import (
    ITEMS_COLLECTION,
    MESSAGES_COLLECTION,
    OUTBOX_INTAKE_TASK,
)
from app.constants.outbox_attention import (
    ATTENTION_SETTINGS_COLLECTION,
    OUTBOX_FLUSH_JOB_ID_PREFIX,
    OUTBOX_FLUSH_TASK,
)
from app.db.mongodb.indexes import create_outbox_indexes
from app.models.chat_models import ConversationSource
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.delivery.presence import end_call, mark_call_live, record_turn_presence
from app.services.outbox.flush import release_on_call_end
from app.services.outbox.intake import submit
from app.services.outbox.models import ComposeResult, OutboxReport
from app.services.outbox.transport.bot_queue import OutboundResult
from app.utils import clock
from app.workers.tasks.outbox_tasks import outbox_flush, outbox_intake
from shared.py.analytics.catalog.delivery import DeliveryItemHeld, DeliveryMessageSent
from tests._harness.judge import ScriptedJudge

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
ROUTER = "app.services.outbox.router"
DELIVER = "app.services.outbox.deliver"
COMPOSE = "app.services.outbox.compose"


class FakeClock:
    """The instant the backend reads; only the timeline moves it."""

    def __init__(self, start: datetime) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current


@dataclass
class _Job:
    run_at: datetime
    args: tuple[Any, ...]
    tries: int = 1


class FakeArq:
    """The ARQ pool: dedupes on _job_id and runs a job only once the clock reaches the instant it is due."""

    def __init__(self, fake_clock: FakeClock) -> None:
        self._clock = fake_clock
        self.jobs: dict[str, _Job] = {}

    async def enqueue_job(
        self,
        function: str,
        *args: Any,
        _job_id: str | None = None,
        _defer_until: datetime | None = None,
        _defer_by: float | None = None,
        **kwargs: Any,
    ) -> object | None:
        assert function in {OUTBOX_INTAKE_TASK, OUTBOX_FLUSH_TASK}, function
        if _job_id in self.jobs:
            return None
        key = _job_id or f"job-{len(self.jobs)}"
        run_at = _defer_until or self._clock.now() + timedelta(seconds=_defer_by or 0)
        self.jobs[key] = _Job(run_at=run_at, args=args)
        return SimpleNamespace(job_id=key)

    async def run_due(self) -> list[str]:
        """Run every job due now, oldest first; a job asking for a retry runs again once it is due, any other exception propagates, as the worker would log it."""
        ran: list[str] = []
        due = sorted(
            (key for key, job in self.jobs.items() if job.run_at <= self._clock.now()),
            key=lambda key: self.jobs[key].run_at,
        )
        for key in due:
            job = self.jobs.pop(key)
            task = outbox_flush if key.startswith(OUTBOX_FLUSH_JOB_ID_PREFIX) else outbox_intake
            try:
                await task({"job_try": job.tries}, *job.args)
            except Retry as retry:
                run_at = self._clock.now() + timedelta(milliseconds=retry.defer_score or 0)
                self.jobs[key] = _Job(run_at=run_at, args=job.args, tries=job.tries + 1)
                continue
            ran.append(key)
        return ran


class ScriptedCompose:
    """The compose model: answers from a script, else tells every item plainly. Records what it was shown."""

    def __init__(self) -> None:
        self.script: list[ComposeResult] = []
        self.calls: list[list[BaseMessage]] = []

    async def __call__(
        self, schema: type[ComposeResult], prompt: list[BaseMessage], **_: object
    ) -> ComposeResult:
        self.calls.append(list(prompt))
        if self.script:
            return self.script.pop(0)
        context = json.loads(str(prompt[1].content))
        items = context["items"]
        return ComposeResult.model_validate(
            {
                "dispositions": [
                    {"item_id": item["item_id"], "action": "include", "reason": "tell it"}
                    for item in items
                ],
                "parts": [f"{item['subject']}: said" for item in items],
            }
        )

    @property
    def context(self) -> dict[str, Any]:
        """What the last call's model input carried."""
        return json.loads(str(self.calls[-1][1].content))


class FakeThreadGraph:
    """The comms graph's thread store: an in-memory checkpoint per conversation, written only under the thread lock."""

    def __init__(self, lock_probe: Callable[[str], Awaitable[bool]]) -> None:
        self.threads: dict[str, list[BaseMessage]] = {}
        self.writes: list[tuple[str, str, bool]] = []
        self._lock_probe = lock_probe

    async def aget_state(self, config: dict[str, Any]) -> SimpleNamespace:
        thread = config["configurable"]["thread_id"]
        return SimpleNamespace(values={"messages": list(self.threads.get(thread, []))})

    async def aupdate_state(
        self, config: dict[str, Any], values: dict[str, Any], as_node: str
    ) -> None:
        thread = config["configurable"]["thread_id"]
        self.writes.append((thread, as_node, await self._lock_probe(thread)))
        self.threads.setdefault(thread, []).extend(values["messages"])


@dataclass
class World:
    """Who the user is and what conversations they have; the router's reads are served from here."""

    user_id: str
    linked: dict[str, str] = field(default_factory=dict)
    priority: list[str] | None = None
    #: platform -> whether the user left it enabled in their notification settings.
    notification_channel_prefs: dict[str, bool] = field(default_factory=dict)
    #: conversation_id -> its source value; None is a chat in the GAIA app.
    conversations: dict[str, str | None] = field(default_factory=dict)
    #: conversation_id -> (platform, platform_user_id, channel_id)
    sessions: dict[str, tuple[str, str, str | None]] = field(default_factory=dict)
    saved: dict[str, list[str]] = field(default_factory=dict)
    unread: set[str] = field(default_factory=set)
    #: Approvals the user can still answer; every other approval is decided or lapsed.
    open_approvals: set[str] = field(default_factory=set)

    def link(self, platform: str, account_id: str) -> None:
        self.linked[platform] = account_id

    def app_chat(self, conversation_id: str) -> None:
        self.conversations[conversation_id] = None

    def dm(self, platform: str, conversation_id: str) -> None:
        self.conversations[conversation_id] = platform
        self.sessions[conversation_id] = (platform, self.linked[platform], None)

    def user_document(self) -> UserDocument:
        return UserDocument.model_validate(
            {
                "id": self.user_id,
                "chat_channel_priority": self.priority,
                "platform_links": {
                    platform: {"id": account, "username": "u", "display_name": "U"}
                    for platform, account in self.linked.items()
                },
                "notification_channel_prefs": self.notification_channel_prefs,
            }
        )

    def dm_conversation_of(self, platform: str) -> str:
        return next(
            conversation_id
            for conversation_id, session in self.sessions.items()
            if session[0] == platform and session[2] is None
        )


@dataclass
class Sinks:
    """What each speech transport was asked to say."""

    bot: list[tuple[str, list[str]]] = field(default_factory=list)
    #: The account id each bot message was addressed to, parallel to `bot`.
    bot_destinations: list[str | None] = field(default_factory=list)
    #: The queue expiry each bot message was published with, parallel to `bot`.
    bot_ttls: list[int | None] = field(default_factory=list)
    #: (platform, what the bot fetches: a URL or an artifact path, caption) for each file sent.
    files: list[tuple[str, str, str | None]] = field(default_factory=list)
    #: The (outbox message id, part index) each file was published under, parallel to `files`.
    file_parts: list[tuple[str | None, int]] = field(default_factory=list)
    ws: list[tuple[str, str]] = field(default_factory=list)
    #: (room, parts) of each message said in a live call.
    voice: list[tuple[str, list[str]]] = field(default_factory=list)
    #: (approval id, body) of each approval push to a backgrounded phone.
    push: list[tuple[str, str]] = field(default_factory=list)
    #: The outbox message id each bot message was published under, parallel to `bot`.
    bot_message_ids: list[str | None] = field(default_factory=list)
    analytics: list[DeliveryMessageSent] = field(default_factory=list)
    held: list[DeliveryItemHeld] = field(default_factory=list)
    bot_result: OutboundResult = OutboundResult.PUBLISHED


@dataclass
class OutboxTimeline:
    """Steps of (minutes since T0, event) played through the real outbox."""

    db: AsyncIOMotorDatabase[Any]
    world: World
    clock: FakeClock
    arq: FakeArq
    compose: ScriptedCompose
    judge: ScriptedJudge
    graph: FakeThreadGraph
    sinks: Sinks

    async def at(self, minutes: float) -> None:
        self.clock.current = T0 + timedelta(minutes=minutes)

    async def submit(self, report: OutboxReport) -> None:
        await submit(report)

    async def drain(self) -> list[str]:
        return await self.arq.run_due()

    async def active_on(self, source: ConversationSource) -> None:
        await record_turn_presence(self.world.user_id, source)

    async def call_starts(self, room: str = "voice_session_room") -> None:
        await mark_call_live(self.world.user_id, room)

    async def call_ends(self, room: str = "voice_session_room") -> None:
        """End the call as the voice worker's last request does: clear it, stamp voice, release what waited."""
        if await end_call(self.world.user_id, room):
            await release_on_call_end(self.world.user_id)

    async def play(self, steps: list[tuple[float, Callable[[], Awaitable[object]]]]) -> None:
        """Run each (minutes, action) in order, moving the clock to its minute first."""
        for minutes, action in steps:
            await self.at(minutes)
            await action()

    async def items(self) -> list[OutboxItemDocument]:
        rows = await self.db[ITEMS_COLLECTION].find({"user_id": self.world.user_id}).to_list(None)
        return [OutboxItemDocument.model_validate({**row, "id": str(row["_id"])}) for row in rows]

    async def ledger(self) -> list[OutboxMessageDocument]:
        rows = (
            await self.db[MESSAGES_COLLECTION]
            .find({"user_id": self.world.user_id})
            .sort("created_at", 1)
            .to_list(None)
        )
        return [
            OutboxMessageDocument.model_validate({**row, "id": str(row["_id"])}) for row in rows
        ]


@contextmanager
def _patched_holds(world: World, sinks: Sinks, arq: FakeArq) -> Iterator[None]:
    """Double the seams the holds and the flush read through: the queue, the user, the held-item event."""

    def capture_held(distinct_id: object, event: DeliveryItemHeld, dedupe: object = None) -> None:
        sinks.held.append(event)

    async def load_user(user_id: str) -> AuthenticatedUser | None:
        return AuthenticatedUser(user_id=user_id) if user_id == world.user_id else None

    with (
        patch(
            "app.services.outbox.flush_queue.RedisPoolManager.get_pool",
            AsyncMock(return_value=arq),
        ),
        patch("app.services.outbox.attention.load_user_context", load_user),
        patch("app.services.outbox.intake.capture", capture_held),
    ):
        yield


@contextmanager
def _approval_doubles(world: World, sinks: Sinks) -> Iterator[None]:
    """Approvals the world holds open, and the push transport they are asked on."""

    async def push(user_id: str, conversation_id: str, approval_id: str, body: str) -> None:
        sinks.push.append((approval_id, body))

    async def is_open(approval_id: str) -> bool:
        return approval_id in world.open_approvals

    with (
        patch(f"{DELIVER}.push_approval_pending", push),
        patch(f"{DELIVER}.is_approval_open", is_open),
    ):
        yield


@contextmanager
def _patched(
    world: World, sinks: Sinks, arq: FakeArq, compose: ScriptedCompose, judge: ScriptedJudge
) -> Iterator[None]:
    async def get_user(user_id: str) -> UserDocument | None:
        return world.user_document() if user_id == world.user_id else None

    async def exists(conversation_id: str, *, user_id: str) -> bool:
        return conversation_id in world.conversations

    async def get_source(conversation_id: str, *, user_id: str) -> ConversationSource | None:
        return ConversationSource.coerce(world.conversations.get(conversation_id))

    async def latest_app(user_id: str) -> str | None:
        return next((c for c, source in world.conversations.items() if source is None), None)

    async def session_of(conversation_id: str) -> SimpleNamespace | None:
        session = world.sessions.get(conversation_id)
        if session is None:
            return None
        return SimpleNamespace(
            platform=session[0], platform_user_id=session[1], channel_id=session[2]
        )

    async def get_or_create_session(
        *, platform: str, platform_user_id: str, channel_id: str | None, user: object, is_dm: bool
    ) -> str:
        return world.dm_conversation_of(platform)

    async def update_messages(request: Any, *, user: object) -> None:
        world.saved.setdefault(request.conversation_id, []).extend(
            m.response for m in request.messages
        )

    async def set_unread(conversation_id: str, *, user_id: str, unread: bool) -> bool:
        world.unread.add(conversation_id)
        return True

    async def publish_bot(
        source: ConversationSource,
        user_id: str,
        parts: list[str],
        *,
        destination_override: str | None = None,
        ttl_seconds: int | None = None,
        outbox_message_id: str | None = None,
    ) -> OutboundResult:
        sinks.bot_message_ids.append(outbox_message_id)
        sinks.bot.append((source.value, list(parts)))
        sinks.bot_destinations.append(destination_override)
        sinks.bot_ttls.append(ttl_seconds)
        return sinks.bot_result

    async def publish_photo(
        platform: ConversationSource,
        user_id: str,
        url: str,
        filename: str,
        caption: str | None = None,
        *,
        outbox_message_id: str | None = None,
        part_index: int = 0,
    ) -> bool:
        sinks.files.append((platform.value, url, caption))
        sinks.file_parts.append((outbox_message_id, part_index))
        return True

    async def publish_file(
        platform: ConversationSource,
        user_id: str,
        conversation_id: str,
        path: str,
        filename: str,
        *,
        outbox_message_id: str | None = None,
        part_index: int = 0,
        **options: str | None,
    ) -> bool:
        sinks.files.append((platform.value, path, options.get("caption")))
        sinks.file_parts.append((outbox_message_id, part_index))
        return True

    async def publish_voice(room_name: str, message_id: str, parts: list[str]) -> bool:
        sinks.voice.append((room_name, list(parts)))
        return True

    async def publish_ws(user_id: str, conversation_id: str, message: dict[str, Any]) -> None:
        sinks.ws.append((conversation_id, message["response"]))

    def capture(distinct_id: object, event: DeliveryMessageSent, dedupe: object = None) -> None:
        sinks.analytics.append(event)

    async def load_user(user_id: str) -> AuthenticatedUser | None:
        return AuthenticatedUser(user_id=user_id) if user_id == world.user_id else None

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch(f"{ROUTER}.user_repository.get", get_user))
        enter(patch(f"{ROUTER}.conversation_repository.exists", exists))
        enter(patch(f"{ROUTER}.conversation_repository.get_source", get_source))
        enter(patch(f"{ROUTER}.conversation_repository.latest_app_conversation_id", latest_app))
        enter(patch(f"{ROUTER}.bot_session_repository.get_by_conversation_id", session_of))
        enter(patch(f"{ROUTER}.BotService.get_or_create_session", get_or_create_session))
        enter(patch(f"{DELIVER}.update_messages", update_messages))
        enter(patch(f"{DELIVER}.conversation_repository.set_unread", set_unread))
        enter(patch(f"{DELIVER}.publish_outbound_message", publish_bot))
        enter(patch(f"{DELIVER}.publish_outbound_photo", publish_photo))
        enter(patch(f"{DELIVER}.publish_outbound_file", publish_file))
        enter(patch(f"{DELIVER}.publish_conversation_message", publish_ws))
        enter(patch(f"{DELIVER}.publish_spoken", publish_voice))
        enter(_approval_doubles(world, sinks))
        enter(patch(f"{DELIVER}.capture", capture))
        enter(patch(f"{DELIVER}.load_user_context", load_user))
        enter(patch(f"{COMPOSE}.ainvoke_structured", compose))
        enter(patch("app.services.outbox.intake.judge_report", judge))
        enter(
            patch(
                "app.services.outbox.intake.RedisPoolManager.get_pool", AsyncMock(return_value=arq)
            )
        )
        enter(_patched_holds(world, sinks, arq))
        yield


async def _release_without_lua(lock: Lock) -> None:
    """Release a redis-py lock the way its Lua script does, which fakeredis (no Lua engine) cannot run."""
    token = lock.local.token
    if await lock.redis.get(lock.name) != (token.decode() if isinstance(token, bytes) else token):
        raise AssertionError(f"{lock.name!r} was released by a holder that no longer owned it")
    await lock.redis.delete(lock.name)


@contextmanager
def outbox_timeline(
    db: AsyncIOMotorDatabase[Any], world: World, fake_redis: Any
) -> Iterator[OutboxTimeline]:
    """Build the timeline's doubles around db and fakeredis, with the production outbox indexes in place."""
    fake_clock = FakeClock(T0)
    arq = FakeArq(fake_clock)
    compose = ScriptedCompose()
    judge = ScriptedJudge()
    sinks = Sinks()

    async def lock_held(thread: str) -> bool:
        return bool(await fake_redis.exists(f"{COMMS_THREAD_LOCK_PREFIX}{thread}"))

    graph = FakeThreadGraph(lock_held)
    with (
        patch.object(clock, "now", fake_clock.now),
        patch.object(Lock, "release", _release_without_lua),
        patch(f"{COMPOSE}.GraphManager.get_graph", AsyncMock(return_value=graph)),
        _patched(world, sinks, arq, compose, judge),
    ):
        yield OutboxTimeline(db, world, fake_clock, arq, compose, judge, graph, sinks)


async def prepare_collections(db: AsyncIOMotorDatabase[Any]) -> None:
    """Empty the outbox collections and build the production indexes on them."""
    for name in (ITEMS_COLLECTION, MESSAGES_COLLECTION, ATTENTION_SETTINGS_COLLECTION):
        await db[name].drop()
    with patch("app.db.mongodb.indexes.get_async_collection", lambda name: db[name]):
        await create_outbox_indexes()


__all__ = [
    "DELIVER",
    "T0",
    "AIMessage",
    "FakeArq",
    "FakeClock",
    "FakeThreadGraph",
    "HumanMessage",
    "OutboxTimeline",
    "ScriptedCompose",
    "Sinks",
    "World",
    "outbox_timeline",
    "prepare_collections",
]
