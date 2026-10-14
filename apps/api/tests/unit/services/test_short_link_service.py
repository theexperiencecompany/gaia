"""Unit tests for short_link_service: mint-loop DuplicateKeyError branching and resolution.

The repository is mocked at the seam. The two unique indexes the loop races
against (slug_unique, target_live_unique) are enforced for real in
tests/contracts/test_short_links_repository.py.
"""

from unittest.mock import AsyncMock, patch

from pymongo.errors import DuplicateKeyError
import pytest

from app.db.repositories.short_links import LIVE_TARGET_UNIQUE_INDEX, SLUG_UNIQUE_INDEX
from app.models.short_link_models import PublicTodoDeliverable, ShortLink, ShortLinkTargetType
from app.services.short_link_service import (
    ShortLinkExhaustedError,
    get_or_create_short_link,
    get_public_file,
    get_public_view,
)

_SVC = "app.services.short_link_service"
TODO = ShortLinkTargetType.TODO_DELIVERABLE
OWNER = "507f1f77bcf86cd799439011"


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
    with patch(f"{_SVC}.short_link_repository") as repo:
        repo.get_live_for_target = AsyncMock(return_value=None)
        repo.get_by_slug = AsyncMock(return_value=None)
        repo.create = AsyncMock()
        yield repo


class TestGetOrCreateShortLink:
    async def test_an_existing_live_link_is_reused_not_reminted(self, repo):
        repo.get_live_for_target.return_value = _link("existing")

        url = await get_or_create_short_link(OWNER, TODO, "t1")

        assert url.endswith("/existing")
        repo.create.assert_not_awaited()

    async def test_losing_a_concurrent_mint_hands_out_the_winners_slug(self, repo):
        """The loser of two overlapping mints returns the winner's link, never a second one."""
        repo.get_live_for_target.side_effect = [None, _link("winner")]
        repo.create.side_effect = _dup(LIVE_TARGET_UNIQUE_INDEX)

        url = await get_or_create_short_link(OWNER, TODO, "t1")

        assert url.endswith("/winner")
        assert repo.create.await_count == 1

    async def test_the_winner_revoked_before_the_reread_mints_again(self, repo):
        repo.create.side_effect = [_dup(LIVE_TARGET_UNIQUE_INDEX), _link("fresh")]

        url = await get_or_create_short_link(OWNER, TODO, "t1")

        assert url.endswith("/fresh")
        assert repo.create.await_count == 2

    async def test_a_slug_collision_draws_another_slug(self, repo):
        repo.create.side_effect = [_dup(SLUG_UNIQUE_INDEX), _link("second")]

        url = await get_or_create_short_link(OWNER, TODO, "t1")

        assert url.endswith("/second")
        assert repo.create.await_count == 2
        assert repo.get_live_for_target.await_count == 1

    async def test_an_unrecognised_unique_violation_propagates(self, repo):
        repo.create.side_effect = _dup("some_other_index")

        with pytest.raises(DuplicateKeyError):
            await get_or_create_short_link(OWNER, TODO, "t1")

    async def test_slug_exhaustion_fails_loudly(self, repo):
        repo.create.side_effect = _dup(SLUG_UNIQUE_INDEX)

        with pytest.raises(ShortLinkExhaustedError):
            await get_or_create_short_link(OWNER, TODO, "t1")


class TestGetPublicView:
    async def test_the_target_is_projected_under_the_links_owner(self, repo):
        repo.get_by_slug.return_value = _link("abc", user_id=OWNER, target_id="t9")
        view = PublicTodoDeliverable(
            target_type=TODO, title="Plan", completed=False, content="Result"
        )
        with patch(f"{_SVC}.project_target", AsyncMock(return_value=view)) as project:
            assert await get_public_view("abc") == view
        project.assert_awaited_once_with(TODO, OWNER, "t9")

    async def test_a_revoked_link_resolves_to_nothing(self, repo):
        repo.get_by_slug.return_value = _link("abc", revoked=True)
        with patch(f"{_SVC}.project_target", AsyncMock()) as project:
            assert await get_public_view("abc") is None
        project.assert_not_awaited()

    async def test_a_deleted_target_resolves_to_nothing(self, repo):
        repo.get_by_slug.return_value = _link("abc")
        with patch(f"{_SVC}.project_target", AsyncMock(return_value=None)):
            assert await get_public_view("abc") is None


class TestGetPublicFile:
    async def test_only_session_artifacts_serve_a_raw_file(self, repo):
        """A todo, briefing or workflow slug never reaches the file route."""
        repo.get_by_slug.return_value = _link("abc", target_type=TODO)
        with patch(f"{_SVC}.session_artifact_file", AsyncMock()) as file_lookup:
            assert await get_public_file("abc") is None
        file_lookup.assert_not_awaited()

    async def test_a_session_artifact_slug_streams_the_owners_file(self, repo, tmp_path):
        repo.get_by_slug.return_value = _link(
            "abc",
            target_type=ShortLinkTargetType.SESSION_ARTIFACT,
            target_id="conv-1/report.pdf",
        )
        with patch(
            f"{_SVC}.session_artifact_file", AsyncMock(return_value=tmp_path)
        ) as file_lookup:
            assert await get_public_file("abc") == tmp_path
        file_lookup.assert_awaited_once_with(OWNER, "conv-1/report.pdf")
