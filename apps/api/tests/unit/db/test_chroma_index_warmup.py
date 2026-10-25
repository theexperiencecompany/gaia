"""Tests for app.db.chroma.index_warmup."""

from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.store.base import PutOp
import pytest

from app.db.chroma.chroma_store import ChromaBatchWriteError
from app.db.chroma.index_warmup import execute_batch_operations, run_index_warmup

# ---------------------------------------------------------------------------
# execute_batch_operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestExecuteBatchOperations:
    async def test_noop_on_empty_ops(self):
        store = AsyncMock()
        await execute_batch_operations(store, [], label="test")
        store.abatch.assert_not_awaited()

    async def test_batches_operations(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(75)]
        await execute_batch_operations(store, ops, label="test", batch_size=50)
        assert store.abatch.await_count == 2

    async def test_every_op_is_written_exactly_once_in_contiguous_batches(self):
        """Each batch is the next batch_size slice, no op dropped, none written twice."""
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(75)]

        await execute_batch_operations(store, ops, label="test", batch_size=50)

        written = [call.args[0] for call in store.abatch.await_args_list]
        assert written == [ops[0:50], ops[50:75]]


# ---------------------------------------------------------------------------
# run_index_warmup
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestRunIndexWarmup:
    async def test_returns_true_on_success(self):
        store = AsyncMock()
        result = await run_index_warmup(store, [], context="tools_store")
        assert result is True

    async def test_returns_false_and_swallows_batch_write_error(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp)]
        with patch(
            "app.db.chroma.index_warmup.execute_batch_operations",
            new_callable=AsyncMock,
            side_effect=ChromaBatchWriteError("1 of 1 ChromaDB writes failed"),
        ):
            result = await run_index_warmup(store, ops, context="tools_store")
        assert result is False
