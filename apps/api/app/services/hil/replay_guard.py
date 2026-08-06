"""Remembering what already ran, so a node's replay does not run it twice.

A gated call pauses with ``interrupt()``; LangGraph discards the node's writes and
replays it on resume. Each tool call is its own node task (``create_agent`` fans them
out with ``Send``), and those tasks are discarded together — so an ungated call that
already completed runs a second time. Verified: one weather lookup became two, and the
second was invisible, because only the replayed ToolMessage ever reached the stream.

Refusing to run the sibling in the first place is not an option: whether the gated call
*will* pause is not knowable before it does — auto mode may approve it outright, and its
gate may fail closed or find an earlier decline — so a call held back would commit a
placeholder for a tool that never ran. That is a worse failure than the double.

What is knowable is that a tool_call_id names exactly one execution. Remember the result
under it and the replay returns what the first pass produced, which is what the model
would have seen had the pause never happened.

Redis, not graph state: the rollback is precisely what throws graph state away.
"""

from typing import Literal, cast

from langchain_core.messages import ToolMessage

from app.constants.hil import HIL_REPLAY_MEMO_KEY_PREFIX, HIL_REPLAY_MEMO_TTL_SECONDS
from app.db.redis import redis_cache
from app.models.hil_models import ToolResultMemo


def _key(conversation_id: str, tool_call_id: str) -> str:
    return f"{HIL_REPLAY_MEMO_KEY_PREFIX}{conversation_id}:{tool_call_id}"


async def remember_tool_result(
    conversation_id: str, tool_call_id: str, result: ToolMessage
) -> None:
    """Record what this call produced, for the replay that may be about to happen."""
    if not redis_cache.redis:
        return
    memo: ToolResultMemo = {
        "content": result.text(),
        "name": result.name or "",
        "status": result.status,
        "additional_kwargs": dict(result.additional_kwargs),
    }
    await redis_cache.set(
        _key(conversation_id, tool_call_id), memo, ttl=HIL_REPLAY_MEMO_TTL_SECONDS
    )


async def recall_tool_result(conversation_id: str, tool_call_id: str) -> ToolMessage | None:
    """What this call produced the last time the node ran, if it got that far."""
    if not redis_cache.redis:
        return None
    raw = await redis_cache.get(_key(conversation_id, tool_call_id))
    if not raw:
        return None
    # Correct by construction: the only writer is ``remember_tool_result`` above.
    memo = cast(ToolResultMemo, raw)
    return ToolMessage(
        content=memo["content"],
        tool_call_id=tool_call_id,
        name=memo["name"],
        status=cast(Literal["success", "error"], memo["status"]),
        additional_kwargs=memo["additional_kwargs"],
    )
