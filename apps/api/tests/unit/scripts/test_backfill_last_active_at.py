"""The last_active_at backfill: a dry run writes nothing, and --apply only ever moves a user forward."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts import backfill_last_active_at as backfill

pytestmark = pytest.mark.unit

_BEHIND = "64f1c0ffee0000000000aaa1"
_AHEAD = "64f1c0ffee0000000000aaa2"


def _usage(rows: list[dict[str, str]]) -> MagicMock:
    async def aggregate(_pipeline: object) -> AsyncIterator[dict[str, str]]:
        for row in rows:
            yield row

    usage = MagicMock()
    usage.aggregate = aggregate
    return usage


def _users(behind: set[str]) -> MagicMock:
    async def count_documents(query: dict[str, object], limit: int) -> int:
        return 1 if str(query["_id"]) in behind else 0

    users = MagicMock()
    users.count_documents = count_documents
    users.update_one = AsyncMock()
    return users


@pytest.fixture
def stores() -> Iterator[MagicMock]:
    users = _users({_BEHIND})
    rows = [{"_id": _BEHIND, "day": "2026-11-15"}, {"_id": _AHEAD, "day": "2026-11-01"}]
    with (
        patch.object(backfill, "usage_daily_collection", _usage(rows)),
        patch.object(backfill, "users_collection", users),
    ):
        yield users


async def test_a_dry_run_counts_the_users_behind_and_writes_nothing(stores: MagicMock) -> None:
    assert await backfill.backfill(apply=False) == 1
    stores.update_one.assert_not_awaited()


async def test_apply_raises_only_the_users_behind_to_their_latest_metered_day(
    stores: MagicMock,
) -> None:
    assert await backfill.backfill(apply=True) == 1

    [update] = stores.update_one.await_args_list
    query, change = update.args
    assert str(query["_id"]) == _BEHIND
    assert change == {"$max": {"last_active_at": datetime(2026, 11, 15, tzinfo=UTC)}}


@pytest.mark.regression
async def test_a_usage_row_metered_to_a_non_user_actor_is_skipped_not_fatal() -> None:
    """Regression: a "system" usage row crashed the release migration on an ObjectId parse."""
    users = _users({_BEHIND})
    rows = [{"_id": "system", "day": "2026-11-20"}, {"_id": _BEHIND, "day": "2026-11-15"}]
    with (
        patch.object(backfill, "usage_daily_collection", _usage(rows)),
        patch.object(backfill, "users_collection", users),
    ):
        assert await backfill.backfill(apply=True) == 1

    [update] = users.update_one.await_args_list
    assert str(update.args[0]["_id"]) == _BEHIND
