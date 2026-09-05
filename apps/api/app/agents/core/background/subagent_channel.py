"""The per-subagent mailbox: how the EXECUTOR steers ONE running subagent.

The executor inbox (:mod:`executor_channel`) carries the user speaking to the
executor. This is its mirror one tier down: a channel the executor writes to —
via its ``message_subagent`` tool — to reach one specific running subagent,
drained by that subagent's own pre-model hook.

Two rules keep it honest:

- **Keyed by the subagent's own thread_id**, so a message addressed to one
  subagent never reaches a sibling. There can be several subagents live at once;
  relevance is per-subagent and only the executor knows it, so the executor
  routes and nothing here broadcasts.
- **Never the executor inbox.** A subagent drains only its own mailbox; work the
  user addressed to the executor stays with the executor.

Storage (:class:`RedisInbox`) and the inject/retire rule (:func:`decide_drain`,
:func:`apply_drain`) are reused from :mod:`executor_channel` so the two tiers
share one canonical mechanism.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.core.background.executor_channel import RedisInbox, apply_drain
from app.constants.agents import AgentTag
from app.constants.cache import (
    SUBAGENT_CANCEL_PREFIX,
    SUBAGENT_CANCEL_TTL,
    SUBAGENT_INBOX_PREFIX,
    SUBAGENT_INBOX_TTL,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import State
from shared.py.wide_events import log


class SubagentInbox(RedisInbox):
    """Steering messages the executor addressed to one running subagent.

    Keyed by the subagent's own thread_id (``<integration>_executor_<conv>`` for a
    handoff, ``spawn_<conv>_<tool_call_id>`` for a spawn), so only the subagent
    running on that thread drains it.
    """

    ttl = SUBAGENT_INBOX_TTL
    default_tag = AgentTag.SUBAGENT_INTERJECTION

    def __init__(self, subagent_thread_id: str) -> None:
        self.subagent_thread_id = subagent_thread_id
        super().__init__(f"{SUBAGENT_INBOX_PREFIX}{subagent_thread_id}")


class SubagentCancel:
    """A targeted stop flag for one running subagent, keyed by its thread_id.

    Set by the executor's ``cancel_subagent`` tool, polled by that subagent's
    stream loop, so a cancel stops exactly that worker — not the executor and not
    a sibling subagent (unlike the stream-scoped cancel, which is shared).
    """

    def __init__(self, subagent_thread_id: str) -> None:
        self._key = f"{SUBAGENT_CANCEL_PREFIX}{subagent_thread_id}"

    async def request(self) -> None:
        """Ask the subagent to stop at its next stream event."""
        if redis_cache.client:
            await redis_cache.client.setex(self._key, SUBAGENT_CANCEL_TTL, "1")

    async def is_requested(self) -> bool:
        """Whether a stop has been asked for."""
        return bool(redis_cache.client and await redis_cache.client.get(self._key))

    async def clear(self) -> None:
        """Drop the flag once the subagent has acted on it."""
        if redis_cache.client:
            await redis_cache.client.delete(self._key)


async def drain_subagent_inbox_hook(
    state: State, config: RunnableConfig, store: BaseStore
) -> State:
    """Pre-model hook: pull steers the executor addressed to THIS subagent.

    Mirrors :func:`drain_inbox_hook` but keyed on the subagent's own thread_id.
    A subagent's run carries its own thread as ``thread_id`` in the configurable,
    so this reads exactly the mailbox ``message_subagent`` wrote for it.
    """
    try:
        thread_id = agent_configurable(config).get("thread_id")
        if not thread_id:
            log.warning(f"{LogTag.AGENT} drain_subagent_inbox_hook: run carries no thread_id")
            return state
        return await apply_drain(SubagentInbox(thread_id), state, log_key="subagent_inbox_injected")
    except Exception as e:  # reading the mailbox must never break the subagent's turn
        log.error(f"{LogTag.AGENT} drain_subagent_inbox_hook failed", error_type=type(e).__name__)
        return state
