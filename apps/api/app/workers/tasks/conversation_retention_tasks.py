"""Daily sweep that drops the tool outputs and thinking from tool cards past their retention.

The card stays (tool name, inputs, message, ids) and a cut output names its full length, so a
client shows that it was cut. An MCP App's tool_result is its app's data and stays whole.
"""

from datetime import UTC, datetime
from typing import cast

from app.constants.conversation import TOOL_OUTPUT_DROP_PAGE, TOOL_OUTPUT_RETENTION
from app.constants.log_tags import LogTag
from app.db.repositories.conversation_output_retention import (
    EntryCards,
    tool_output_retention_repository,
)
from app.services.conversation.tool_cards import dropped_outputs
from app.utils.errors import ConversationStoreError
from app.workers.task_envelope import ArqJobContext
from shared.py.conversation_wire import ToolDataEntry
from shared.py.wide_events import log


async def drop_expired_tool_outputs(_ctx: ArqJobContext) -> str:
    """Cut every entry committed more than TOOL_OUTPUT_RETENTION ago, a page at a time, until none is left."""
    cutoff = datetime.now(UTC) - TOOL_OUTPUT_RETENTION
    entries = bytes_freed = 0
    while page := await tool_output_retention_repository.list_unswept(
        cutoff, TOOL_OUTPUT_DROP_PAGE
    ):
        cut = [_cut(entry) for entry in page]
        stored = await tool_output_retention_repository.store_cut(cut)
        if not stored:
            # Every write of the page found its entry changed: the read and the write disagree.
            raise ConversationStoreError(
                message="the tool output retention sweep stored no entry of a page",
                meta={"page": str(len(page))},
            )
        entries += stored
        bytes_freed += sum(was.stored_bytes - now.stored_bytes for was, now in zip(page, cut))
    summary = {"entries_cut": entries, "bytes_freed": bytes_freed}
    log.set(tool_output_retention=summary)
    log.info(f"{LogTag.WORKER} expired tool outputs dropped", **summary)
    return f"entries={entries} bytes_freed={bytes_freed}"


def _cut(entry: EntryCards) -> EntryCards:
    # Stored cards are the ToolDataEntry dicts the log wrote; read raw so no key is lost.
    cards = dropped_outputs(cast(list[ToolDataEntry], entry.tool_data))
    return entry.model_copy(update={"tool_data": [dict(card) for card in cards]})
