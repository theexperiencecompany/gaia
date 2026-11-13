"""The live channel by which new work reaches a RUNNING executor.

One executor runs per conversation. This module enforces one rule:

    An inbox entry always becomes a message inside an executor run.
    It never becomes a run of its own.

So an entry carries only {id, text}. Nothing about a run is stored here — every
writer already holds the context it would need to start one.

Storage, framing, the drain decision and the hook that applies it live together
here on purpose: they are one mechanism. The only piece elsewhere is the commit
itself, in the vendored model node (pop_injected_messages) — a pre-model hook's
return shapes the model input and is never checkpointed, so the hook stages and
the node commits.
"""

import json
from typing import NotRequired, TypedDict, cast
from uuid import uuid4

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from redis.asyncio.client import Pipeline
from redis.exceptions import ResponseError

from app.agents.core.background.executor_queue import decode_raw_item
from app.constants.agents import NON_WAKING_TAGS, AgentTag, wrap_agent_payload
from app.constants.cache import EXECUTOR_INBOX_PREFIX
from app.constants.executor import INBOX_ENTRY_ID, INTERRUPTION_NOTICE
from app.constants.hil import EXECUTOR_INBOX_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable, InboxDrain, InboxEntry, agent_configurable
from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY, State
from app.services.cost_budget import restart_request_tokens
from shared.py.wide_events import log


class _StoredInboxEntry(TypedDict):
    """The JSON one inbox entry is stored as; tag is absent on entries written before it existed."""

    id: str
    text: str
    tag: NotRequired[str]


def decide_drain(entries: list[InboxEntry], messages: list[AnyMessage]) -> InboxDrain:
    """Split pending entries into "inject now" and "already landed, drop it".

    Pure, so the channel's rule is testable without Redis or a graph. An entry is
    retired only once it is visible in the thread, never when merely read, so a
    run that dies between reading and committing loses nothing.
    """
    committed = {message.additional_kwargs.get(INBOX_ENTRY_ID) for message in messages}
    inject = [entry for entry in entries if entry.id not in committed]
    retire = [entry for entry in entries if entry.id in committed]
    return InboxDrain(inject=inject, retire=retire)


def as_interjection(entry: InboxEntry) -> HumanMessage:
    """Frame an entry as the user speaking mid-run.

    A HumanMessage, not a SystemMessage: it lands in the CONVERSATION slot, the
    only accumulating one, so it reads to the model like the request that started
    the run. The tag marks it as internal framing and is stripped before the user.
    """
    return HumanMessage(
        content=wrap_agent_payload(entry.tag, entry.text),
        additional_kwargs={INBOX_ENTRY_ID: entry.id},
    )


class RedisInbox:
    """A Redis-list mailbox: append, non-destructive read, targeted retire.

    The shared mechanics behind both the conversation-level executor inbox and
    the per-subagent mailbox, so the two tiers never drift in how an entry is
    stored, framed, or retired. Reads never remove; retire is the only removal,
    so the channel is safe to read from a run that may die at any point.
    Subclasses only choose the key, TTL, and default tag; the drain rule stays in
    decide_drain.
    """

    #: Entry expiry; a subclass overrides for its own channel.
    ttl: int = EXECUTOR_INBOX_TTL
    #: Tag applied to an append that names no tag of its own.
    default_tag: AgentTag = AgentTag.USER_INTERJECTION

    def __init__(self, key: str) -> None:
        self._key = key

    @staticmethod
    def _encode(entry: InboxEntry) -> str:
        """Encode deterministically so retire can remove the exact value append wrote."""
        stored: _StoredInboxEntry = {"id": entry.id, "text": entry.text, "tag": entry.tag.value}
        return json.dumps(stored, sort_keys=True)

    async def append(self, entry_id: str, text: str, tag: AgentTag | None = None) -> InboxEntry:
        """Add pending work for whichever run reads this channel next."""
        entry = InboxEntry(id=entry_id, text=text, tag=tag or self.default_tag)
        if redis_cache.client:
            await redis_cache.client.rpush(self._key, self._encode(entry))
            await redis_cache.client.expire(self._key, self.ttl)
        return entry

    def stage_append(self, pipe: Pipeline, entry: InboxEntry) -> None:
        """Queue the same append on pipe, for a write the entry must land with or not at all."""
        pipe.rpush(self._key, self._encode(entry))
        pipe.expire(self._key, self.ttl)

    async def read(self) -> list[InboxEntry]:
        """Every pending entry, oldest first. Does not remove anything."""
        if not redis_cache.client:
            return []
        raw_entries = await redis_cache.client.lrange(self._key, 0, -1)
        return [entry for raw in raw_entries if (entry := _decode(raw)) is not None]

    async def retire(self, entry: InboxEntry) -> None:
        """Drop an entry that is now committed to the reading run's thread."""
        if redis_cache.client:
            await redis_cache.client.lrem(self._key, 1, self._encode(entry))

    async def count(self) -> int:
        """How much work is waiting. Cheap enough to ask before every decision."""
        return await redis_cache.client.llen(self._key) if redis_cache.client else 0

    async def keep_for(self, seconds: int) -> None:
        """Keep what is waiting for at least seconds from now: a hold that long may keep its reader away."""
        await redis_cache.client.expire(self._key, seconds)


class ExecutorInbox(RedisInbox):
    """Pending messages for one conversation's executor.

    Not a queue: see the module docstring. Reads are non-destructive and retire
    is the only removal, so the inbox is safe to read from a run that may die at
    any point — and what has actually been delivered is read off the executor's
    thread (decide_drain), never off a marker here that could disagree with it.
    """

    ttl = EXECUTOR_INBOX_TTL
    default_tag = AgentTag.USER_INTERJECTION

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"{EXECUTOR_INBOX_PREFIX}{conversation_id}")

    async def clear(self) -> int:
        """Drop all pending work, keeping the notices a stop left; return how much work went.

        RENAME detaches the list in one atomic step, so a steering append that lands
        mid-cancel starts a fresh list under the live key and survives; a
        count-then-delete would sweep it away. Non-waking notices go back to the
        head of the live list: they are not work.
        """
        client = redis_cache.client
        if not client:
            return 0
        detached = f"{self._key}:clearing:{uuid4().hex}"
        try:
            await client.rename(self._key, detached)
        except ResponseError:
            return 0  # RENAME raises "no such key" only when the inbox is empty
        raw_entries = await client.lrange(detached, 0, -1)
        notices = [
            entry
            for raw in raw_entries
            if (entry := _decode(raw)) is not None and entry.tag in NON_WAKING_TAGS
        ]
        # Mutating transaction= is equivalent: the detached uuid key has no other writer.
        async with client.pipeline(transaction=True) as pipe:  # pragma: no mutate
            pipe.delete(detached)
            for notice in reversed(notices):
                pipe.lpush(self._key, self._encode(notice))
            if notices:
                pipe.expire(self._key, self.ttl)
            await pipe.execute()
        return len(raw_entries) - len(notices)

    async def announce_interruption(self, message: str | None = None) -> list[InboxEntry]:
        """Tell the next run that the one before it was force-stopped.

        The per-conversation thread persists, so a cancelled run leaves its
        abandoned task in history; without this note the next run picks it back
        up. A redirect ("stop that, do X instead") is a separate entry, not folded
        into the notice — folding once made a bare Stop look like pending work.
        """
        entries = [
            await self.append(str(uuid4()), INTERRUPTION_NOTICE, AgentTag.EXECUTOR_INTERRUPTED)
        ]
        if message:
            entries.append(await self.append(str(uuid4()), message))
        return entries

    async def discard(self, entry_ids: set[str]) -> list[str]:
        """Drop the named entries; return the ids actually removed.

        Entry ids are the task_id the dispatching tool minted, so a user
        cancelling "that second thing I asked for" reaches work still pending
        here as well as work already running.
        """
        removed = [entry for entry in await self.read() if entry.id in entry_ids]
        for entry in removed:
            await self.retire(entry)
        return [entry.id for entry in removed]


def _decode(raw: bytes | memoryview | str) -> InboxEntry | None:
    """Decode one stored entry, skipping anything unreadable.

    A malformed entry is dropped rather than raised on: it would otherwise wedge
    the channel for the whole conversation, and there is nothing to recover from
    a value we cannot parse. It is logged so it is not silent.
    """
    try:
        text = decode_raw_item(raw)
        payload: _StoredInboxEntry = json.loads(text)
        return InboxEntry(
            id=payload["id"],
            text=payload["text"],
            tag=AgentTag(payload.get("tag", AgentTag.USER_INTERJECTION)),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.warning(f"{LogTag.AGENT} Discarding unreadable executor inbox entry")
        return None


async def apply_drain(
    inbox: RedisInbox, state: State, *, log_key: str
) -> tuple[State, list[InboxEntry]]:
    """Read a mailbox, retire what the thread already holds, inject the rest; return what was injected.

    Shared by the executor inbox and the per-subagent mailbox so both tiers inject
    and retire identically. Staged under INJECTED_MESSAGES_KEY because a hook's own
    return is discarded after the call; the model node commits it.
    """
    entries = await inbox.read()
    if not entries:
        return state, []

    messages = state.get("messages", [])
    drain = decide_drain(entries, messages)
    for entry in drain.retire:
        await inbox.retire(entry)

    if not drain.inject:
        return state, []

    injected = [as_interjection(entry) for entry in drain.inject]
    log.set(**{log_key: len(injected)})
    staged = cast(
        State,
        {**state, "messages": [*messages, *injected], INJECTED_MESSAGES_KEY: injected},
    )
    return staged, drain.inject


async def drain_inbox_hook(state: State, config: RunnableConfig, store: BaseStore) -> State:  # noqa: ARG001 -- execute_hooks() passes state/config/store positionally
    """Pre-model hook: pull pending work into the run that is already going.

    Runs before every executor model call, so work handed over mid-run lands on
    the next reasoning step rather than the next run.
    """
    try:
        # conversation_id, never thread_id: the executor graph runs on the WRAPPED
        # thread (executor_<conversation>), so keying the inbox on thread_id builds
        # executor:inbox:executor_<conv> and silently never matches call_executor.
        configurable: AgentConfigurable = agent_configurable(config)
        conversation_id = configurable.get("conversation_id")
        if not conversation_id:
            log.warning(f"{LogTag.AGENT} drain_inbox_hook: run carries no conversation_id")
            return state
        drained, injected = await apply_drain(
            ExecutorInbox(conversation_id), state, log_key="executor_inbox_injected"
        )
        user_spoke = any(entry.tag is AgentTag.USER_INTERJECTION for entry in injected)
        root_request_id = configurable.get("root_request_id")
        if user_spoke and root_request_id:
            # A message absorbed mid-run is a new user turn: give it a fresh token ceiling.
            await restart_request_tokens(root_request_id)
            log.set(request_ceiling_restarted=True)
        return drained
    except Exception as e:  # reading the inbox must never break the turn
        log.error(f"{LogTag.AGENT} drain_inbox_hook failed", error_type=type(e).__name__)
        return state
