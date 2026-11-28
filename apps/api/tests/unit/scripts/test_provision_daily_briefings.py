"""The existing-user briefing rollout boots like an entry point.

Regression: the rollout reports each user's path through capture(), which needs a bound
analytics context and a registered PostHog provider; without them every user failed.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from scripts.provision_daily_briefings import rollout

from app.services.briefing.rollout import RolloutPath
from app.services.workflow.scheduler import workflow_scheduler
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import current_analytics_context

MODULE = "scripts.provision_daily_briefings"


@pytest.fixture(autouse=True)
def _analytics_context() -> None:
    """Leave the context unbound: the script is an entry point and must bind its own."""


@pytest.fixture(autouse=True)
def job_queue() -> Iterator[AsyncMock]:
    """Stand in for the Redis job queue the rollout opens to arm each workflow's schedule."""
    pool = AsyncMock()
    with patch("app.services.scheduler_service.create_pool", AsyncMock(return_value=pool)):
        yield pool
    workflow_scheduler.arq_pool = None


async def _path_needing_a_context(user_id: str) -> RolloutPath:
    assert current_analytics_context().attribution.trigger is Trigger.SYSTEM
    return RolloutPath.NORMAL


async def test_every_user_is_rolled_out_under_a_bound_analytics_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(f"{MODULE}.boot_process") as register,
        patch(f"{MODULE}.user_repository.list_all_ids", AsyncMock(return_value=["u1", "u2"])),
        patch(f"{MODULE}.provision_existing_user", side_effect=_path_needing_a_context),
    ):
        await rollout(apply=True)

    # A script has no app lifespan: it boots (loop + the providers capture() and the
    # workflow provisioning read), or every user fails on "Provider not found".
    register.assert_called_once_with("main_app")
    assert "[APPLY] done: 2/2; breakdown={'normal': 2}" in capsys.readouterr().out


async def test_a_dry_run_counts_the_users_and_provisions_nobody() -> None:
    with (
        patch(f"{MODULE}.user_repository.list_all_ids", AsyncMock(return_value=["u1", "u2"])),
        patch(f"{MODULE}.provision_existing_user", AsyncMock()) as provision,
    ):
        assert await rollout(apply=False) == {}

    provision.assert_not_awaited()


@pytest.mark.regression
async def test_every_user_is_rolled_out_with_the_job_queue_open(job_queue: AsyncMock) -> None:
    queues_seen: list[object] = []

    async def _path_recording_the_queue(user_id: str) -> RolloutPath:
        queues_seen.append(workflow_scheduler.arq_pool)
        return RolloutPath.NORMAL

    with (
        patch(f"{MODULE}.boot_process"),
        patch(f"{MODULE}.user_repository.list_all_ids", AsyncMock(return_value=["u1", "u2"])),
        patch(f"{MODULE}.provision_existing_user", side_effect=_path_recording_the_queue),
    ):
        await rollout(apply=True)

    # Without a queue every workflow the rollout creates is stored but never armed.
    assert queues_seen == [job_queue, job_queue]
    job_queue.aclose.assert_awaited_once()
