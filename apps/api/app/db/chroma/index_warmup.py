"""Provide shared batch execution and failure tolerance for ChromaDB catalog/index warmup.

Tool and trigger indexing both run at startup as best-effort enrichment. A write
failure, typically the embedding provider being unavailable, must be surfaced
loudly but must never abort boot. The low-level abatch stays fail-loud (it
raises ChromaBatchWriteError); this is the one place that tolerates that raise.
"""

from __future__ import annotations

from langgraph.store.base import PutOp

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

from .chroma_store import ChromaBatchWriteError, ChromaStore

_DEFAULT_BATCH_SIZE = 50


async def execute_batch_operations(
    store: ChromaStore,
    put_ops: list[PutOp],
    *,
    label: str,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> None:
    """Apply put operations to a ChromaStore in batches.

    Propagates ChromaBatchWriteError if any write in a batch fails.
    """
    if not put_ops:
        return

    total_ops = len(put_ops)
    for i in range(0, total_ops, batch_size):
        await store.abatch(put_ops[i : i + batch_size])
        log.info(
            f"{LogTag.CHROMA} Processed index warmup batch",
            label=label,
            batch_index=i // batch_size + 1,
            batch_total=(total_ops + batch_size - 1) // batch_size,
        )


async def run_index_warmup(store: ChromaStore, put_ops: list[PutOp], *, context: str) -> bool:
    """Best-effort catalog/index warmup: on a batch-write failure, log loud and degrade.

    Returns True when every write succeeded (or there was nothing to write) and
    False when the batch failed — so a caller can skip caching a success hash and
    let the next boot retry. A failure is never fatal: index warmup is enrichment,
    and the loud error keeps a real outage visible instead of a silent zero-row pass.
    """
    try:
        await execute_batch_operations(store, put_ops, label=context)
    except ChromaBatchWriteError as exc:
        log.error(
            f"{LogTag.CHROMA} Index warmup batch write failed, leaving catalog degraded for next-boot retry",
            context=context,
            error_type=type(exc).__name__,
        )
        return False
    return True
