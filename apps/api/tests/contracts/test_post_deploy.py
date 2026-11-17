"""The post-deploy step against real Mongo: each migration once, in order, a failure retried."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from scripts import post_deploy


def _steps(*names: str) -> dict[str, AsyncMock]:
    return {name: AsyncMock() for name in names}


@pytest.fixture
def steps(raw_collection, monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    fakes = _steps("first", "second")
    monkeypatch.setattr(post_deploy, "deploy_steps", raw_collection)
    monkeypatch.setattr(post_deploy, "POST_DEPLOY_STEPS", tuple(fakes.items()))
    return fakes


async def test_a_dry_run_runs_each_step_as_a_dry_run_and_marks_nothing(
    steps: dict[str, AsyncMock], raw_collection
) -> None:
    assert await post_deploy.run_post_deploy(apply=False) == []

    for step in steps.values():
        step.assert_awaited_once_with(apply=False)
    assert await raw_collection.count_documents({}) == 0


async def test_each_step_applies_once_in_order_and_never_again(
    steps: dict[str, AsyncMock],
) -> None:
    assert await post_deploy.run_post_deploy(apply=True) == ["first", "second"]
    assert await post_deploy.run_post_deploy(apply=True) == []

    for step in steps.values():
        step.assert_awaited_once_with(apply=True)


async def test_a_failed_step_stops_the_run_and_is_retried_next_time(
    steps: dict[str, AsyncMock],
) -> None:
    steps["first"].side_effect = [RuntimeError("mongo blip"), None]

    with pytest.raises(RuntimeError, match="mongo blip"):
        await post_deploy.run_post_deploy(apply=True)
    steps["second"].assert_not_awaited()

    assert await post_deploy.run_post_deploy(apply=True) == ["first", "second"]


async def test_a_claim_a_live_runner_holds_is_left_to_it_and_a_stale_one_taken_over(
    steps: dict[str, AsyncMock], raw_collection
) -> None:
    now = datetime.now(UTC)
    await raw_collection.insert_many(
        [
            {"_id": "first", "claimed_at": now, "applied_at": None},
            {"_id": "second", "claimed_at": now - timedelta(days=1), "applied_at": None},
        ]
    )

    assert await post_deploy.run_post_deploy(apply=True) == ["second"]
    steps["first"].assert_not_awaited()
