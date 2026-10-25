#!/usr/bin/env python3
"""One-time repair of comms thread history polluted by the message-break ratchet.

Stored comms replies used to end in an appended break; the model copied its own
history and each turn added one, up to 3,998-break replies. Every comms reply is
rewritten to its normalized form under the same id; a reply left with nothing
(and no tool call) is removed. Threads written in the last IDLE_BEFORE_REPAIR are
reported and skipped. Save the --apply output: each line carries the checkpoint
to resume from to roll a thread back.

Run from the api directory (or /app inside the container):

    python scripts/repair_comms_message_breaks.py           # report only (default)
    python scripts/repair_comms_message_breaks.py --apply   # rewrite the threads
"""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.constants.general import NEW_MESSAGE_BREAKER
from app.core.provider_registration import register_lazy_providers
from app.utils.message_breaks import normalize_message_breaks

COMMS_GRAPH = "comms_agent"
IDLE_BEFORE_REPAIR = timedelta(minutes=10)
# Comms threads are keyed by the bare conversation uuid; executor/subagent threads carry a prefix.
CANDIDATE_THREADS_SQL = """
SELECT thread_id FROM checkpoint_writes
 WHERE checkpoint_ns = '' AND channel = 'messages' AND position(%(needle)s IN blob) > 0
   AND thread_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
UNION
SELECT thread_id FROM checkpoint_blobs
 WHERE checkpoint_ns = '' AND channel = 'messages' AND position(%(needle)s IN blob) > 0
   AND thread_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
"""


@dataclass(frozen=True, slots=True)
class ThreadReport:
    thread_id: str
    checkpoint_before: str | None
    rewritten: int
    removed: int
    skipped_busy: bool


def repair_writes(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Return same-id normalized copies of polluted comms replies, or removals when nothing is left."""
    writes: list[BaseMessage] = []
    for message in messages:
        if not isinstance(message, AIMessage) or not isinstance(message.content, str):
            continue
        normalized = normalize_message_breaks(message.content)
        if normalized == message.content:
            continue
        if message.id is None:
            raise ValueError("a checkpointed AIMessage has no id; it cannot be replaced in place")
        if normalized or message.tool_calls:
            writes.append(message.model_copy(update={"content": normalized}))
        else:
            writes.append(RemoveMessage(id=message.id))
    return writes


async def candidate_threads() -> list[str]:
    manager = await get_checkpointer_manager()
    if manager.pool is None:
        raise RuntimeError("checkpointer pool is not open")
    async with manager.pool.connection() as conn:
        cursor = await conn.execute(
            CANDIDATE_THREADS_SQL, {"needle": (NEW_MESSAGE_BREAKER * 2).encode()}
        )
        return sorted(str(row[0]) for row in await cursor.fetchall())


async def repair_thread(
    graph: CompiledAgentGraph, thread_id: str, *, apply: bool, now: datetime
) -> ThreadReport:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)
    writes = repair_writes(state.values.get("messages", []))
    removed = sum(isinstance(write, RemoveMessage) for write in writes)
    busy = (
        state.created_at is not None
        and now - datetime.fromisoformat(state.created_at) < IDLE_BEFORE_REPAIR
    )
    if apply and writes and not busy:
        await graph.aupdate_state(config, {"messages": writes}, as_node="tools")
    checkpoint_before = state.config.get("configurable", {}).get("checkpoint_id")
    return ThreadReport(thread_id, checkpoint_before, len(writes) - removed, removed, busy)


async def _run(*, apply: bool) -> None:
    # A script has no lifespan, so nobody registers the lazy providers otherwise.
    register_lazy_providers("arq_worker")
    manager = await get_checkpointer_manager()
    try:
        graph = await GraphManager.get_graph(COMMS_GRAPH)
        now = datetime.now(UTC)
        print("APPLIED" if apply else "DRY RUN: nothing was written")
        for thread_id in await candidate_threads():
            print(await repair_thread(graph, thread_id, apply=apply, now=now))
        if not apply:
            print("\nRe-run with --apply to rewrite them.")
    finally:
        await manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="rewrite the threads (default: report)"
    )
    asyncio.run(_run(apply=parser.parse_args().apply))


if __name__ == "__main__":
    main()
