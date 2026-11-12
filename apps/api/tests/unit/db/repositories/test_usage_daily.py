"""The usage-daily repository's window-totals read over a faked aggregate cursor."""

from collections.abc import AsyncIterator, Mapping
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest

from app.db.repositories.usage_daily import UsageDailyRepository


def _collection(rows: list[Mapping[str, object]]) -> MagicMock:
    async def cursor() -> AsyncIterator[Mapping[str, object]]:
        for row in rows:
            yield row

    collection = MagicMock()
    collection.aggregate = MagicMock(return_value=cursor())
    return collection


async def test_window_totals_pair_each_user_with_their_summed_count() -> None:
    repo = UsageDailyRepository()
    rows = [{"_id": "u1", "total": 7}, {"_id": "u2", "total": 0}]
    collection = _collection(rows)
    with patch.object(repo, "_raw_collection", return_value=collection):
        totals = await repo.user_window_totals("2026-11-01")

    assert totals == [("u1", 7), ("u2", 0)]
    [pipeline] = collection.aggregate.call_args.args
    assert pipeline[0] == {"$match": {"date": {"$gte": "2026-11-01"}}}


async def test_a_window_total_row_without_a_user_fails_loudly() -> None:
    repo = UsageDailyRepository()
    with (
        patch.object(repo, "_raw_collection", return_value=_collection([{"total": 3}])),
        pytest.raises(ValidationError),
    ):
        await repo.user_window_totals("2026-11-01")
