"""The live step stack an e2e drives: both real graphs on the real checkpointer, models scripted.

The fixtures that open it (open_stack, owner, checkpointer) live in tests/e2e/conftest.py.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import Entry
from app.services.conversation.event_stream import replay_from_log
from app.services.conversation.mongo_log import MongoConversationLog
from tests.e2e._harness.graph_run import StreamingScriptedModel

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"
RESET_MODULE = "app.services.checkpoint_thread_reset"
CONVERSATIONS_MODULE = "app.services.conversation_service"

OWNED_COLLECTIONS = (
    "todos",
    "conversations",
    CONVERSATION_ENTRIES_COLLECTION,
    "notifications",
    "approval_ledger",
)


@dataclass
class Stack:
    """The live pieces one test drives, and what they recorded."""

    checkpointer: CheckpointerManager
    executor_model: StreamingScriptedModel
    comms_model: StreamingScriptedModel
    #: Every WebSocket event a client of the user would have received, in order.
    pushed: list[dict[str, Any]] = field(default_factory=list)

    def pushed_of(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.pushed if event.get("type") == kind]

    async def threads_of(self, conversation_id: str) -> dict[str, str]:
        """Each Postgres checkpoint thread the conversation owns, by its oldest checkpoint id."""
        assert self.checkpointer.pool is not None
        async with self.checkpointer.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT thread_id, min(checkpoint_id) FROM checkpoints "
                "WHERE thread_id LIKE %s GROUP BY thread_id",
                (f"%{conversation_id}%",),
            )
            return {row[0]: row[1] for row in await cur.fetchall()}

    async def wipe_threads_of(self, conversation_id: str) -> None:
        checkpointer = self.checkpointer.get_checkpointer()
        for thread_id in await self.threads_of(conversation_id):
            await checkpointer.adelete_thread(thread_id)


OpenStack = Callable[..., AbstractAsyncContextManager[Stack]]

_E = TypeVar("_E")


async def replayed(conversation_id: str, user_id: str) -> list[Entry]:
    """Return what a device connecting to the conversation's events receives: the log's replay."""
    log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
    frames = await replay_from_log(log, conversation_id, user_id, 0)
    return [frame.frame.entry for frame in frames if isinstance(frame.frame, EntryFrame)]


def entries_of(shown: list[Entry], kind: type[_E]) -> list[_E]:
    return [entry for entry in shown if isinstance(entry, kind)]
