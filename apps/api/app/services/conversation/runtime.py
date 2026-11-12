"""The production conversation runtime: the one place RuntimePorts are built, and the steps it runs in this process.

A kick starts advance as a tracked task; while the process drains for shutdown it starts
none, and the sweeper (or the next process) advances what was left.
"""

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import cache

from app.agents.core.background.work_cancel import cancel_named_work
from app.constants.conversation import STEP_TICK_SECONDS
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import EntryUpdatedFrame
from app.models.conversation_log_models import (
    LoggedEntry,
    Reaction,
    Reply,
    UserMessage,
)
from app.services.conversation.ack import decide_reaction
from app.services.conversation.approval_replies import HilApprovalReplies
from app.services.conversation.comms_runner import CommsGraphRunner
from app.services.conversation.comms_turn import build_comms_turn
from app.services.conversation.event_stream import RedisStreamFrames
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.step import advance
from app.utils.background_tasks import spawn_background_task

# The entries before a message the instant reaction reads GAIA's previous words from.
_REACTION_CONTEXT_ENTRIES = 20


def _now() -> datetime:
    return datetime.now(UTC)


async def _tick() -> None:
    await asyncio.sleep(STEP_TICK_SECONDS)


class _Steps:
    """The steps running in this process, and whether it still starts new ones."""

    def __init__(self) -> None:
        self.running: set[asyncio.Task[None]] = set()
        self.draining = False


_steps = _Steps()


class RuntimeEffects:
    """The Effects port: start a step, cancel named work, react to a just-accepted message."""

    def __init__(
        self,
        log: MongoConversationLog,
        frames: RedisStreamFrames,
        ports: Callable[[], RuntimePorts],
    ) -> None:
        self._log = log
        self._frames = frames
        self._ports = ports

    async def kick(self, conversation_id: str, user_id: str) -> None:
        """Start advancing the conversation here, unless this process is draining for shutdown."""
        if _steps.draining:
            return
        task = spawn_background_task(
            advance(self._ports(), conversation_id, user_id), name="conversation_step"
        )
        _steps.running.add(task)
        task.add_done_callback(_steps.running.discard)

    async def cancel_work(
        self, conversation_id: str, user_id: str, task_ids: tuple[str, ...]
    ) -> None:
        """Cancel exactly the named tasks, running or queued, and the approvals of a stopped run."""
        await cancel_named_work(conversation_id, user_id, list(task_ids))

    async def start_ack(self, conversation_id: str, user_id: str, message_id: str) -> None:
        """Decide the instant reaction beside the step; the accept that asked never waits for it."""
        spawn_background_task(
            self._react(conversation_id, user_id, message_id), name="conversation_instant_reaction"
        )

    async def _react(self, conversation_id: str, user_id: str, message_id: str) -> None:
        state = await self._log.state(conversation_id, user_id)
        recent = await self._log.read_after(
            conversation_id, user_id, max(0, state.head - _REACTION_CONTEXT_ENTRIES)
        )
        said = next(
            (
                logged.entry
                for logged in recent
                if isinstance(logged.entry, UserMessage) and logged.entry.id == message_id
            ),
            None,
        )
        if said is None:
            return
        decision = await decide_reaction(said.text, _previous_reply_text(recent, message_id))
        if decision.emoji is None:
            return
        reacted = await self._log.react_once(
            conversation_id, user_id, message_id, Reaction(emoji=decision.emoji, by=ReactionBy.JEV)
        )
        if reacted is not None:
            await self._frames.publish(
                conversation_id, EntryUpdatedFrame(seq=reacted.seq, entry=reacted.entry)
            )


def _previous_reply_text(recent: Sequence[LoggedEntry], message_id: str) -> str:
    """Return GAIA's last reply before the message, or empty when it opens the conversation."""
    text = ""
    for logged in recent:
        if logged.entry.id == message_id:
            break
        if isinstance(logged.entry, Reply) and logged.entry.text:
            text = logged.entry.text
    return text


@cache
def runtime_ports() -> RuntimePorts:
    """Return the production ports: the Mongo log, the comms graph runner, the Redis frames stream."""
    log = MongoConversationLog(conversation_log_repository, _now)
    frames = RedisStreamFrames()
    return RuntimePorts(
        log=log,
        runner=CommsGraphRunner(build_comms_turn),
        frames=frames,
        effects=RuntimeEffects(log, frames, runtime_ports),
        approvals=HilApprovalReplies(),
        clock=_now,
        tick=_tick,
    )


async def drain_steps(grace_seconds: float) -> int:
    """Stop starting steps and wait up to grace_seconds for the running ones; return how many were cut off."""
    _steps.draining = True
    running = tuple(_steps.running)
    if not running:
        return 0
    _done, pending = await asyncio.wait(running, timeout=grace_seconds)
    for task in pending:
        task.cancel()
    return len(pending)
