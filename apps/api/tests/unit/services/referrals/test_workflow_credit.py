"""Remix credit: only a subscribed creator of a community workflow gets the visitor's signup."""

from collections.abc import Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user_models import UserDocument
from app.services.referrals.workflow_credit import workflow_creator_code

MODULE = "app.services.referrals.workflow_credit"
CREATOR = UserDocument(id="64a0000000000000000000c1", first_name="Cara")


def _workflow(*, is_explore: bool = False, created_by: str | None = CREATOR.id) -> SimpleNamespace:
    return SimpleNamespace(is_explore=is_explore, created_by=created_by)


@dataclass
class Seams:
    workflow: AsyncMock
    creator: AsyncMock
    subscription: AsyncMock
    ensure_code: AsyncMock
    log: MagicMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    with (
        patch(
            f"{MODULE}.workflow_repository.get_public_with_creator",
            AsyncMock(return_value=_workflow()),
        ) as workflow,
        patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=CREATOR)) as creator,
        patch(
            f"{MODULE}.subscription_repository.get_active_for_user",
            AsyncMock(return_value=object()),
        ) as subscription,
        patch(f"{MODULE}.ensure_code", AsyncMock(return_value="cara-x2y3")) as ensure_code,
        patch(f"{MODULE}.log") as log,
    ):
        yield Seams(workflow, creator, subscription, ensure_code, log)


async def test_a_subscribed_creators_community_workflow_credits_their_code(seams: Seams) -> None:
    assert await workflow_creator_code("wf-1") == "cara-x2y3"

    seams.workflow.assert_awaited_once_with("wf-1", by_slug=False)
    seams.creator.assert_awaited_once_with(CREATOR.id)
    seams.subscription.assert_awaited_once_with(CREATOR.id)
    seams.ensure_code.assert_awaited_once_with(CREATOR)
    seams.log.set_ns.assert_called_once_with(
        "referral", workflow_credit="eligible", referrer_id=CREATOR.id
    )


@pytest.mark.parametrize(
    "workflow",
    [None, _workflow(is_explore=True), _workflow(created_by=None)],
    ids=["unknown", "curated-explore", "no-creator"],
)
async def test_a_workflow_with_no_community_creator_credits_nobody(
    seams: Seams, workflow: SimpleNamespace | None
) -> None:
    seams.workflow.return_value = workflow

    assert await workflow_creator_code("wf-1") is None
    seams.creator.assert_not_awaited()
    seams.log.set_ns.assert_called_once_with("referral", workflow_credit="not_community")


async def test_a_deleted_creator_credits_nobody(seams: Seams) -> None:
    seams.creator.return_value = None

    assert await workflow_creator_code("wf-1") is None
    seams.subscription.assert_not_awaited()
    seams.log.set_ns.assert_called_once_with("referral", workflow_credit="creator_missing")


async def test_a_creator_without_a_subscription_has_no_link_to_credit(seams: Seams) -> None:
    seams.subscription.return_value = None

    assert await workflow_creator_code("wf-1") is None
    seams.ensure_code.assert_not_awaited()
    seams.log.set_ns.assert_called_once_with("referral", workflow_credit="creator_not_subscribed")
