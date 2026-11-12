"""The mint loop's branches: slug collisions, losing a concurrent mint, exhaustion, and GAIA-attached failures.

The repository is mocked at the seam; the unique indexes these branches race
against are enforced for real in tests/contracts/test_short_links_repository.py,
and the full share/open/revoke flow runs over real Mongo in
tests/integration/real/test_links_real.py.
"""

import re
from unittest.mock import AsyncMock, patch

from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import pytest

from app.db.repositories.short_links import LIVE_TARGET_UNIQUE_INDEX, SLUG_UNIQUE_INDEX
from app.models.short_link_models import LinkSettings, ShortLink, ShortLinkTargetType
from app.services.links.service import (
    MAX_SLUG_ATTEMPTS,
    ShortLinkExhaustedError,
    optional_short_link,
    share,
)
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.short_links import ShortLinkCreated
from tests.helpers import captured_wide_event

_SVC = "app.services.links.service"
TODO = ShortLinkTargetType.TODO_DELIVERABLE
OWNER = "507f1f77bcf86cd799439011"
# 11 base62 characters: the capability must survive guessing.
SLUG_SHAPE = re.compile(r"[A-Za-z0-9]{11}")


def _dup(index: str) -> DuplicateKeyError:
    """Build a DuplicateKeyError shaped exactly like Mongo raises it for index."""
    msg = f"E11000 duplicate key error collection: gaia.short_links index: {index} dup key: {{ x: 1 }}"
    return DuplicateKeyError(msg, 11000, {"errmsg": msg, "code": 11000})


def _link(slug: str, **overrides: object) -> ShortLink:
    data: dict[str, object] = {
        "slug": slug,
        "user_id": OWNER,
        "target_type": TODO,
        "target_id": "t1",
    }
    data.update(overrides)
    return ShortLink.model_validate(data)


@pytest.fixture
def repo():
    with (
        patch(f"{_SVC}.short_link_repository") as repo,
        patch(f"{_SVC}._snapshot_for", AsyncMock(return_value=None)),
        patch(f"{_SVC}._release_snapshot", AsyncMock()),
    ):
        repo.get_live_for_target = AsyncMock(return_value=None)
        repo.get_latest_for_target = AsyncMock(return_value=None)
        repo.create = AsyncMock()
        yield repo


@pytest.fixture
def capture():
    with patch(f"{_SVC}.capture") as capture:
        yield capture


async def _share() -> ShortLink:
    return await share(OWNER, TODO, "t1", LinkSettings())


class TestShare:
    async def test_an_existing_live_link_is_reused_not_reminted(self, repo):
        repo.get_live_for_target.return_value = _link("existing")

        assert (await _share()).slug == "existing"
        repo.create.assert_not_awaited()

    async def test_a_first_mint_stores_a_fresh_capability_slug_for_the_owner(self, repo, capture):
        repo.create.side_effect = lambda link: link

        minted = await _share()

        (stored,), _ = repo.create.await_args
        assert SLUG_SHAPE.fullmatch(stored.slug)
        assert (stored.user_id, stored.target_type, stored.target_id) == (OWNER, TODO, "t1")
        assert stored.revoked is False
        assert minted.slug == stored.slug
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkCreated(
                target_type=TODO.value, access="unlisted", origin="owner_share", has_expiry=False
            ),
        )

    async def test_losing_a_concurrent_mint_hands_out_the_winners_link(self, repo):
        repo.get_live_for_target.side_effect = [None, _link("winner")]
        repo.create.side_effect = _dup(LIVE_TARGET_UNIQUE_INDEX)

        assert (await _share()).slug == "winner"
        assert repo.create.await_count == 1

    async def test_the_winner_revoked_before_the_reread_mints_again(self, repo):
        repo.create.side_effect = [_dup(LIVE_TARGET_UNIQUE_INDEX), _link("fresh")]

        assert (await _share()).slug == "fresh"
        assert repo.create.await_count == 2

    async def test_a_slug_collision_draws_another_slug(self, repo):
        repo.create.side_effect = [_dup(SLUG_UNIQUE_INDEX), _link("second")]

        assert (await _share()).slug == "second"
        assert repo.create.await_count == 2
        first, second = (call.args[0].slug for call in repo.create.await_args_list)
        assert first != second

    async def test_an_unrecognised_unique_violation_propagates(self, repo):
        repo.create.side_effect = _dup("some_other_index")

        with pytest.raises(DuplicateKeyError):
            await _share()

    async def test_slug_exhaustion_fails_loudly(self, repo):
        repo.create.side_effect = _dup(SLUG_UNIQUE_INDEX)

        async with captured_wide_event() as event:
            with pytest.raises(ShortLinkExhaustedError) as raised:
                await _share()

        assert str(raised.value) == (
            f"Could not mint a unique slug for user {OWNER} after {MAX_SLUG_ATTEMPTS} attempts"
        )
        assert repo.create.await_count == MAX_SLUG_ATTEMPTS
        assert event["errors"] == [{"msg": "short_link.slug_exhausted", "user_id": OWNER}]


class TestGaiaAttachedLinks:
    @pytest.mark.parametrize(
        "failure",
        [
            ServerSelectionTimeoutError("no primary"),
            AppError(message="web risk down", status_code=503),
        ],
    )
    async def test_a_failure_costs_only_the_link(self, repo, failure):
        repo.get_latest_for_target.side_effect = failure

        async with captured_wide_event() as event:
            assert await optional_short_link(OWNER, TODO, "t1") is None

        assert event["errors"][0]["msg"] == "short_link.mint_failed"

    async def test_a_first_attachment_mints_as_gaia_attached(self, repo, capture):
        repo.create.side_effect = lambda link: link

        url = await optional_short_link(OWNER, TODO, "t1")

        assert url is not None
        assert capture.call_args.args[1].origin == "gaia_attached"
