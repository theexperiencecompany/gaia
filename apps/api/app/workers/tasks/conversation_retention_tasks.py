"""Daily sweep that drops the tool outputs and thinking from tool cards past their retention.

The card stays (tool name, inputs, message, ids) and a cut output names its full length; a
card left with nothing, such as one that held only thinking, is removed. An MCP App's
tool_result is its app's data and stays whole.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import time
from typing import cast

from app.constants.conversation import TOOL_OUTPUT_DROP_PAGE, TOOL_OUTPUT_RETENTION
from app.constants.log_tags import LogTag
from app.db.repositories.conversation_output_retention import (
    EntryCards,
    tool_output_retention_repository,
)
from app.services.conversation.tool_cards import dropped_outputs
from app.utils.errors import ConversationStoreError
from app.workers.config.worker_settings import WORKER_JOB_TIMEOUT_SECONDS
from app.workers.task_envelope import ArqJobContext
from shared.py.conversation_wire import ToolDataEntry
from shared.py.wide_events import log

#: Half the envelope's deadline: a run stops between pages well before it is cut off.
RUN_BUDGET_SECONDS = WORKER_JOB_TIMEOUT_SECONDS / 2
#: The run's clock; a test steps it instead of the process-wide one the event loop schedules by.
clock = time.monotonic


@dataclass
class _Totals:
    entries_cut: int = 0
    bytes_freed: int = 0
    # Entries that changed between read and write this run; the next run cuts them.
    entries_passed_over: int = 0
    out_of_time: bool = False


async def drop_expired_tool_outputs(_ctx: ArqJobContext) -> str:
    """Cut every entry committed more than TOOL_OUTPUT_RETENTION ago, a page at a time.

    Stops between pages once RUN_BUDGET_SECONDS is spent; the next daily run carries on.
    """
    cutoff = datetime.now(UTC) - TOOL_OUTPUT_RETENTION
    started = clock()
    totals = _Totals()
    passed_over: set[str] = set()
    while page := await tool_output_retention_repository.list_unswept(
        cutoff, TOOL_OUTPUT_DROP_PAGE, excluding=passed_over
    ):
        cut = {entry.id: _cut(entry) for entry in page}
        written = await tool_output_retention_repository.store_cut(list(cut.values()))
        if not written:
            # Every entry of the page changed since it was read: the read and the write disagree.
            raise ConversationStoreError(
                message="the tool output retention sweep stored no entry of a page",
                meta={"page": str(len(page))},
            )
        passed_over |= cut.keys() - written
        totals.entries_cut += len(written)
        totals.bytes_freed += sum(
            was.stored_bytes - cut[was.id].stored_bytes for was in page if was.id in written
        )
        if clock() - started >= RUN_BUDGET_SECONDS:
            totals.out_of_time = True
            break
    totals.entries_passed_over = len(passed_over)
    log.set(tool_output_retention=asdict(totals))
    log.info(f"{LogTag.WORKER} expired tool outputs dropped", **asdict(totals))
    return f"entries={totals.entries_cut} bytes_freed={totals.bytes_freed}"


def _cut(entry: EntryCards) -> EntryCards:
    # Stored cards are the ToolDataEntry dicts the log wrote; read raw so no key is lost.
    cards = dropped_outputs(cast(list[ToolDataEntry], entry.tool_data))
    return entry.model_copy(update={"tool_data": [dict(card) for card in cards]})
