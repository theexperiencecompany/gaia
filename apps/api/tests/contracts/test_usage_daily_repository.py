"""Contract tests for UsageDailyRepository — the durable per-day usage rollup.

This is billing data: it is the ONLY per-day history of what a user's spend and
tokens were, because the Redis budget windows expire in ~26h. A ``$inc`` that
lands in the wrong field books charged work as free background COGS (or the
reverse), and a pruned field that should have been written loses the raw usage a
mispriced call has to be re-derived from. Real Mongo, so the ``$inc``-upsert and
the ``$gte`` date window under test are the real ones.
"""

from __future__ import annotations

import pytest

from app.db.repositories.usage_daily import UsageDailyRepository

USER = "user-rollup-1"
OTHER_USER = "user-rollup-2"
DAY = "2026-03-04"


@pytest.fixture
def repo(raw_collection) -> UsageDailyRepository:
    # Depends on ``raw_collection`` so the repository's collection accessor is
    # pointed at this test's throwaway collection, even when the test body
    # never touches the raw handle itself.
    return UsageDailyRepository()


class TestIncrement:
    async def test_upserts_a_new_row_carrying_every_named_amount(self, repo, raw_collection):
        await repo.increment(
            USER,
            DAY,
            count=1,
            cost=0.02,
            input_tokens=300,
            output_tokens=120,
            cached_tokens=50,
            reasoning_tokens=40,
        )

        raw = await raw_collection.find_one({"user_id": USER, "date": DAY})
        assert raw is not None
        assert raw["count"] == 1
        assert raw["cost"] == pytest.approx(0.02)
        assert raw["input_tokens"] == 300
        assert raw["output_tokens"] == 120
        assert raw["cached_tokens"] == 50
        assert raw["reasoning_tokens"] == 40

    async def test_accumulates_into_the_same_day_instead_of_replacing_it(
        self, repo, raw_collection
    ):
        await repo.increment(USER, DAY, count=1, cost=0.02, input_tokens=300, output_tokens=120)
        await repo.increment(USER, DAY, count=1, cost=0.03, input_tokens=200, output_tokens=80)

        assert await raw_collection.count_documents({"user_id": USER, "date": DAY}) == 1
        raw = await raw_collection.find_one({"user_id": USER, "date": DAY})
        assert raw["count"] == 2
        assert raw["cost"] == pytest.approx(0.05)
        assert raw["input_tokens"] == 500
        assert raw["output_tokens"] == 200

    async def test_a_second_day_is_its_own_row(self, repo, raw_collection):
        await repo.increment(USER, DAY, count=1, input_tokens=10)
        await repo.increment(USER, "2026-03-05", count=1, input_tokens=99)

        assert await raw_collection.count_documents({"user_id": USER}) == 2
        second = await raw_collection.find_one({"user_id": USER, "date": "2026-03-05"})
        assert second["input_tokens"] == 99

    async def test_amounts_left_at_zero_are_not_written_at_all(self, repo, raw_collection):
        await repo.increment(USER, DAY, count=1)

        raw = await raw_collection.find_one({"user_id": USER, "date": DAY})
        # Pruning zeros keeps a row honest about what it has actually seen: a
        # `cost: 0` key is indistinguishable from "we priced this at $0".
        assert "cost" not in raw
        assert "input_tokens" not in raw
        assert "aux_cost" not in raw

    async def test_an_all_zero_call_writes_no_document(self, repo, raw_collection):
        await repo.increment(USER, DAY)

        assert await raw_collection.count_documents({}) == 0

    async def test_charged_tokens_never_leak_into_the_auxiliary_mirrors(self, repo, raw_collection):
        await repo.increment(
            USER,
            DAY,
            cost=0.02,
            input_tokens=300,
            output_tokens=120,
            cached_tokens=50,
            reasoning_tokens=40,
        )

        raw = await raw_collection.find_one({"user_id": USER, "date": DAY})
        assert "aux_cost" not in raw
        assert "aux_input_tokens" not in raw
        assert "aux_output_tokens" not in raw
        assert "aux_cached_tokens" not in raw
        assert "aux_reasoning_tokens" not in raw

    async def test_auxiliary_tokens_never_leak_into_the_charged_fields(self, repo, raw_collection):
        await repo.increment(
            USER,
            DAY,
            aux_cost=0.02,
            aux_input_tokens=300,
            aux_output_tokens=120,
            aux_cached_tokens=50,
            aux_reasoning_tokens=40,
        )

        raw = await raw_collection.find_one({"user_id": USER, "date": DAY})
        assert raw["aux_input_tokens"] == 300
        assert raw["aux_output_tokens"] == 120
        assert raw["aux_cached_tokens"] == 50
        assert raw["aux_reasoning_tokens"] == 40
        assert "cost" not in raw
        assert "input_tokens" not in raw
        assert "output_tokens" not in raw
        assert "cached_tokens" not in raw
        assert "reasoning_tokens" not in raw

    async def test_charged_and_auxiliary_work_on_the_same_day_stay_separate(
        self, repo, raw_collection
    ):
        await repo.increment(USER, DAY, cost=0.02, input_tokens=300, reasoning_tokens=40)
        await repo.increment(USER, DAY, aux_cost=0.05, aux_input_tokens=900, aux_reasoning_tokens=7)

        raw = await raw_collection.find_one({"user_id": USER, "date": DAY})
        assert raw["cost"] == pytest.approx(0.02)
        assert raw["input_tokens"] == 300
        assert raw["reasoning_tokens"] == 40
        assert raw["aux_cost"] == pytest.approx(0.05)
        assert raw["aux_input_tokens"] == 900
        assert raw["aux_reasoning_tokens"] == 7


class TestRollupsSince:
    async def test_returns_the_boundary_day_and_drops_the_one_before_it(self, repo):
        await repo.increment(USER, "2026-03-02", count=1, input_tokens=1)
        await repo.increment(USER, "2026-03-03", count=1, input_tokens=2)
        await repo.increment(USER, "2026-03-04", count=1, input_tokens=3)

        rows = await repo.rollups_since(USER, "2026-03-03")

        assert {row.date for row in rows} == {"2026-03-03", "2026-03-04"}

    async def test_carries_the_full_token_breakdown_not_just_the_count(self, repo):
        await repo.increment(
            USER,
            DAY,
            count=2,
            cost=0.02,
            input_tokens=300,
            output_tokens=120,
            cached_tokens=50,
            reasoning_tokens=40,
        )

        (row,) = await repo.rollups_since(USER, DAY)

        assert row.count == 2
        assert row.cost == pytest.approx(0.02)
        assert row.input_tokens == 300
        assert row.output_tokens == 120
        assert row.cached_tokens == 50
        assert row.reasoning_tokens == 40

    async def test_is_scoped_to_the_asking_user(self, repo):
        await repo.increment(USER, DAY, count=1, input_tokens=5)
        await repo.increment(OTHER_USER, DAY, count=9, input_tokens=900)

        (row,) = await repo.rollups_since(USER, DAY)

        assert row.user_id == USER
        assert row.input_tokens == 5

    async def test_a_row_written_before_the_token_fields_existed_reads_back_as_zeros(
        self, repo, raw_collection
    ):
        # Every rollup already in production predates the token columns; the
        # activity chart sums these, so a missing field must read 0, not blow up.
        await raw_collection.insert_one({"user_id": USER, "date": DAY, "count": 4, "cost": 0.01})

        (row,) = await repo.rollups_since(USER, DAY)

        assert row.count == 4
        assert row.input_tokens == 0
        assert row.output_tokens == 0
        assert row.cached_tokens == 0
        assert row.reasoning_tokens == 0
        assert row.aux_input_tokens == 0

    async def test_no_rows_in_the_window_is_an_empty_list(self, repo):
        await repo.increment(USER, "2026-03-01", count=1)

        assert await repo.rollups_since(USER, "2026-03-02") == []


class TestCountsSince:
    async def test_projects_the_window_down_to_date_to_count(self, repo):
        await repo.increment(USER, "2026-03-03", count=2, input_tokens=300)
        await repo.increment(USER, "2026-03-04", count=5, input_tokens=700)

        assert await repo.counts_since(USER, "2026-03-03") == {"2026-03-03": 2, "2026-03-04": 5}

    async def test_a_day_with_spend_but_no_metered_action_counts_zero(self, repo):
        # Auxiliary background work books cost/tokens without a `count`; the
        # heatmap must not light that day up as user activity.
        await repo.increment(USER, DAY, aux_cost=0.04, aux_input_tokens=800)

        assert await repo.counts_since(USER, DAY) == {DAY: 0}
