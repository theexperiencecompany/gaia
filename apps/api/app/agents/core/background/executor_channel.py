"""The live channel by which new work reaches a RUNNING executor.

One executor runs per conversation. Before this module, work handed over while
that executor was busy went onto a FIFO of serialized *run requests*, so an
entry had two possible destinies — absorbed by the live run, or spawned as a
second run with its own stream and its own separate answer. "Give the executor
work" therefore meant two different things depending on timing.

This module replaces that with one rule:

    An inbox entry always becomes a message inside an executor run.
    It never becomes a run of its own.

So an entry carries only ``{id, text}``. Nothing about a run is stored here —
every writer already holds the context it would need to start one, which is the
only reason the old queue serialized run context at all.

Storage, framing, the drain decision and the hook that applies it live together
in this file on purpose. They are one mechanism: splitting the "what do we
inject" rule away from the "where is it kept" rule is what makes a channel like
this unreadable. The only piece elsewhere is the commit itself, in the vendored
model node (:func:`pop_injected_messages`) — a pre-model hook's return shapes
the model input and is never checkpointed, so the hook stages and the node
commits.
"""

from dataclasses import dataclass
import json
from typing import cast
from uuid import uuid4

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.core.background.executor_queue import decode_raw_item
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.cache import EXECUTOR_INBOX_PREFIX, EXECUTOR_INBOX_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY, State
from shared.py.wide_events import log

#: Stamped onto an injected message so a later pass recognises it as already
#: committed to the thread. This is the whole basis of the drain's idempotency:
#: the thread itself is the record of what has been delivered, so no cursor has
#: to be kept in sync with it.
INBOX_ENTRY_ID = "inbox_entry_id"

#: What a stopped run tells the run that follows it. Carries no instruction of
#: its own, which is why it never counts as work (see ``announce_interruption``).
INTERRUPTION_NOTICE = (
    "The task you were working on was INTERRUPTED by the user. Do not "
    "resume it, retry it, or finish what it left half-done unless the "
    "user asks for it again."
)


@dataclass(frozen=True, slots=True)
class InboxEntry:
    """One thing the executor has not been told yet.

    ``tag`` decides how it reads to the model: ordinary work is the user
    speaking, an interruption is the system reporting that a task was stopped.
    """

    id: str
    text: str
    tag: AgentTag = AgentTag.USER_INTERJECTION


@dataclass(frozen=True, slots=True)
class InboxDrain:
    """What a single drain pass decided to do."""

    inject: list[InboxEntry]
    retire: list[InboxEntry]

    def __bool__(self) -> bool:
        return bool(self.inject or self.retire)


def decide_drain(entries: list[InboxEntry], messages: list[AnyMessage]) -> InboxDrain:
    """Split pending entries into "inject now" and "already landed, drop it".

    Pure, so the rule that governs the channel can be tested without Redis or a
    graph. An entry is retired only once it is *visible in the thread*, never
    when it is merely read — a run that dies between reading and committing
    therefore loses nothing, because it never removed anything.
    """
    committed = {
        message.additional_kwargs.get(INBOX_ENTRY_ID)
        for message in messages
        if getattr(message, "additional_kwargs", None)
    }
    inject = [entry for entry in entries if entry.id not in committed]
    retire = [entry for entry in entries if entry.id in committed]
    return InboxDrain(inject=inject, retire=retire)


def as_interjection(entry: InboxEntry) -> HumanMessage:
    """Frame an entry as the user speaking mid-run.

    A ``HumanMessage`` and not a ``SystemMessage``: it lands in the CONVERSATION
    slot, which is the only accumulating one, so it reads to the model exactly
    like the request that started the run. The tag marks it as internal framing
    and is stripped before anything reaches the user.
    """
    return HumanMessage(
        content=wrap_agent_payload(entry.tag, entry.text),
        additional_kwargs={INBOX_ENTRY_ID: entry.id},
    )


class ExecutorInbox:
    """Pending messages for one conversation's executor.

    Not a queue: see the module docstring. Reads are non-destructive and
    ``retire`` is the only removal, so the inbox is safe to read from a run that
    may die at any point — and what has actually been delivered is read off the
    executor's thread (:func:`decide_drain`), never off a marker here that could
    disagree with it.
    """

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._key = f"{EXECUTOR_INBOX_PREFIX}{conversation_id}"

    @staticmethod
    def _encode(entry: InboxEntry) -> str:
        """Deterministic, so ``retire`` can remove the exact value ``append`` wrote."""
        return json.dumps(
            {"id": entry.id, "text": entry.text, "tag": entry.tag.value}, sort_keys=True
        )

    async def append(
        self, entry_id: str, text: str, tag: AgentTag = AgentTag.USER_INTERJECTION
    ) -> InboxEntry:
        """Add pending work for whichever executor run reads next."""
        entry = InboxEntry(id=entry_id, text=text, tag=tag)
        if redis_cache.client:
            await redis_cache.client.rpush(self._key, self._encode(entry))
            await redis_cache.client.expire(self._key, EXECUTOR_INBOX_TTL)
        return entry

    async def read(self) -> list[InboxEntry]:
        """Every pending entry, oldest first. Does not remove anything."""
        if not redis_cache.client:
            return []
        raw_entries = await redis_cache.client.lrange(self._key, 0, -1)
        return [entry for raw in raw_entries if (entry := _decode(raw)) is not None]

    async def retire(self, entry: InboxEntry) -> None:
        """Drop an entry that is now committed to the executor's thread."""
        if redis_cache.client:
            await redis_cache.client.lrem(self._key, 1, self._encode(entry))

    async def count(self) -> int:
        """How much work is waiting. Cheap enough to ask before every decision."""
        return await redis_cache.client.llen(self._key) if redis_cache.client else 0

    async def clear(self) -> int:
        """Drop everything pending. Returns how many entries went."""
        pending = await self.count()
        if redis_cache.client:
            await redis_cache.client.delete(self._key)
        return pending

    async def announce_interruption(self, message: str | None = None) -> list[InboxEntry]:
        """Tell the next run that the one before it was force-stopped.

        The executor's thread is per-conversation and persists, so a cancelled
        run leaves its abandoned task sitting in that history. Without this note
        the next run reads it as unfinished business and picks it straight back
        up — which is exactly what the user stopped. Committing the stop into the
        same thread is what makes an interrupt actually mean stop.

        A redirect ("stop that, do X instead") is appended as its own entry
        rather than folded into the notice. The notice is context for whatever
        the user does next and is never work in its own right; folding them
        together made a bare Stop look like pending work, and finalize started
        a fresh run whose task WAS the stop notice.
        """
        entries = [
            await self.append(str(uuid4()), INTERRUPTION_NOTICE, AgentTag.EXECUTOR_INTERRUPTED)
        ]
        if message:
            entries.append(await self.append(str(uuid4()), message))
        return entries

    async def discard(self, entry_ids: set[str]) -> list[str]:
        """Drop the named entries. Returns the ids actually removed.

        Entry ids are the ``task_id`` the dispatching tool minted, so a user
        cancelling "that second thing I asked for" reaches work that is still
        pending here as well as work already running.
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
        payload = json.loads(text)
        return InboxEntry(
            id=payload["id"],
            text=payload["text"],
            tag=AgentTag(payload.get("tag", AgentTag.USER_INTERJECTION)),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.warning(f"{LogTag.AGENT} Discarding unreadable executor inbox entry")
        return None


async def drain_inbox_hook(state: State, config: RunnableConfig, store: BaseStore) -> State:  # noqa: ARG001 -- execute_hooks() passes state/config/store positionally
    """Pre-model hook: pull pending work into the run that is already going.

    Runs before every executor model call, so work handed over mid-run lands on
    the next reasoning step rather than the next run. Staged under
    ``INJECTED_MESSAGES_KEY`` because a hook's own return is discarded after the
    call — the model node commits it.
    """
    try:
        # ``conversation_id``, never ``thread_id``: the executor graph runs on the
        # WRAPPED thread (``executor_<conversation>``), so keying the inbox on
        # thread_id builds ``executor:inbox:executor_<conv>`` and silently never
        # matches what ``call_executor`` wrote. AgentConfigurable documents this.
        conversation_id = agent_configurable(config).get("conversation_id")
        if not conversation_id:
            log.warning(f"{LogTag.AGENT} drain_inbox_hook: run carries no conversation_id")
            return state

        inbox = ExecutorInbox(conversation_id)
        entries = await inbox.read()
        if not entries:
            return state

        messages = state.get("messages", [])
        drain = decide_drain(entries, messages)
        for entry in drain.retire:
            await inbox.retire(entry)

        if not drain.inject:
            return state

        injected = [as_interjection(entry) for entry in drain.inject]
        log.set(executor_inbox_injected=len(injected))
        return cast(
            State,
            {**state, "messages": [*messages, *injected], INJECTED_MESSAGES_KEY: injected},
        )
    except Exception as e:  # reading the inbox must never break the turn
        log.error(f"{LogTag.AGENT} drain_inbox_hook failed", error_type=type(e).__name__)
        return state
