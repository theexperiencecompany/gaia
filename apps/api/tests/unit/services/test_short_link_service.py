"""Unit tests for short_link_service: mint-loop DuplicateKeyError branching and resolution.

The repository is mocked at the seam. The two unique indexes the loop races
against (slug_unique, target_live_unique) are enforced for real in
tests/contracts/test_short_links_repository.py.
"""

from datetime import UTC, datetime
import re
from unittest.mock import AsyncMock, patch

from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import pytest

from app.db.repositories.short_links import LIVE_TARGET_UNIQUE_INDEX, SLUG_UNIQUE_INDEX
from app.models.short_link_models import (
    LinkViewer,
    LinkViewerKind,
    PublicTodoDeliverable,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.short_link_service import (
    MAX_SLUG_ATTEMPTS,
    ShortLinkExhaustedError,
    get_public_file,
    get_public_view,
    live_share_url,
    optional_short_link,
    record_open,
    share_short_link,
    stop_sharing,
)
from app.utils.log_identifiers import hash_short_link_slug
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.short_links import (
    ShortLinkCreated,
    ShortLinkOpened,
    ShortLinkRevoked,
)
from tests.helpers import captured_wide_event

_SVC = "app.services.short_link_service"
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
    with patch(f"{_SVC}.short_link_repository") as repo:
        repo.get_live_for_target = AsyncMock(return_value=None)
        repo.get_latest_for_target = AsyncMock(return_value=None)
        repo.get_by_slug = AsyncMock(return_value=None)
        repo.create = AsyncMock()
        yield repo


@pytest.fixture
def capture():
    with patch(f"{_SVC}.capture") as capture:
        yield capture


class TestShareShortLink:
    async def test_an_existing_live_link_is_reused_not_reminted(self, repo):
        repo.get_live_for_target.return_value = _link("existing")

        url = await share_short_link(OWNER, TODO, "t1")

        assert url.endswith("/existing")
        repo.create.assert_not_awaited()
        repo.get_live_for_target.assert_awaited_once_with(OWNER, TODO, "t1")

    async def test_a_first_mint_stores_a_fresh_capability_slug_for_the_owner(self, repo, capture):
        repo.create.side_effect = lambda link: link

        url = await share_short_link(OWNER, TODO, "t1")

        (stored,), _ = repo.create.await_args
        assert SLUG_SHAPE.fullmatch(stored.slug)
        assert (stored.user_id, stored.target_type, stored.target_id) == (OWNER, TODO, "t1")
        assert stored.revoked is False
        assert url.endswith(f"/{stored.slug}")
        capture.assert_called_once_with(UserId(OWNER), ShortLinkCreated(target_type=TODO.value))

    async def test_losing_a_concurrent_mint_hands_out_the_winners_slug(self, repo):
        """The loser of two overlapping mints returns the winner's link, never a second one."""
        repo.get_live_for_target.side_effect = [None, _link("winner")]
        repo.create.side_effect = _dup(LIVE_TARGET_UNIQUE_INDEX)

        url = await share_short_link(OWNER, TODO, "t1")

        assert url.endswith("/winner")
        assert repo.create.await_count == 1
        assert repo.get_live_for_target.await_args_list[1].args == (OWNER, TODO, "t1")

    async def test_the_winner_revoked_before_the_reread_mints_again(self, repo):
        repo.create.side_effect = [_dup(LIVE_TARGET_UNIQUE_INDEX), _link("fresh")]

        url = await share_short_link(OWNER, TODO, "t1")

        assert url.endswith("/fresh")
        assert repo.create.await_count == 2

    async def test_a_slug_collision_draws_another_slug(self, repo):
        repo.create.side_effect = [_dup(SLUG_UNIQUE_INDEX), _link("second")]

        url = await share_short_link(OWNER, TODO, "t1")

        assert url.endswith("/second")
        assert repo.create.await_count == 2
        assert repo.get_live_for_target.await_count == 1

    async def test_an_unrecognised_unique_violation_propagates(self, repo):
        repo.create.side_effect = _dup("some_other_index")

        with pytest.raises(DuplicateKeyError):
            await share_short_link(OWNER, TODO, "t1")

    async def test_slug_exhaustion_fails_loudly(self, repo):
        repo.create.side_effect = _dup(SLUG_UNIQUE_INDEX)

        async with captured_wide_event() as event:
            with pytest.raises(ShortLinkExhaustedError) as raised:
                await share_short_link(OWNER, TODO, "t1")

        assert str(raised.value) == (
            f"Could not mint a unique slug for user {OWNER} after {MAX_SLUG_ATTEMPTS} attempts"
        )
        assert event["errors"] == [
            {
                "msg": "short_link.slug_exhausted",
                "user_id": OWNER,
                "target_type": TODO.value,
                "target_id": "t1",
            }
        ]


class TestGetPublicView:
    async def test_the_target_is_projected_under_the_links_owner(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc", user_id=OWNER, target_id="t9")
        view = PublicTodoDeliverable(
            target_type=TODO, title="Plan", completed=False, content="Result"
        )
        with patch(f"{_SVC}.project_target", AsyncMock(return_value=view)) as project:
            assert await get_public_view("abc") == view
        project.assert_awaited_once_with(TODO, OWNER, "t9")
        repo.get_by_slug.assert_awaited_once_with("abc")
        # Resolving is a read: SSR, prefetchers and unfurl bots all resolve, so none of it is an open.
        capture.assert_not_called()

    async def test_a_revoked_link_resolves_to_nothing(self, repo):
        repo.get_by_slug.return_value = _link("abc", revoked=True)
        with patch(f"{_SVC}.project_target", AsyncMock()) as project:
            assert await get_public_view("abc") is None
        project.assert_not_awaited()

    async def test_a_deleted_target_resolves_to_nothing(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc")
        with patch(f"{_SVC}.project_target", AsyncMock(return_value=None)):
            assert await get_public_view("abc") is None
        capture.assert_not_called()


VIEWER_IP = "198.51.100.7"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/605.1.15 Safari/605.1.15"
OTHER_USER = "507f1f77bcf86cd799439022"


def _anonymous(ip: str = VIEWER_IP, user_agent: str = BROWSER_UA) -> LinkViewer:
    return LinkViewer(user_id=None, ip=ip, user_agent=user_agent)


def _opened_dedupe(capture) -> Dedupe:
    ((_, _, dedupe), _) = capture.call_args
    return dedupe


class TestRecordOpen:
    async def test_a_recipient_opening_the_link_counts_once_for_the_owner(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc")

        kind = await record_open("abc", _anonymous())

        assert kind is LinkViewerKind.RECIPIENT
        ((distinct_id, event, dedupe), _) = capture.call_args
        assert distinct_id == UserId(OWNER)
        assert event == ShortLinkOpened(target_type=TODO.value, viewer_signed_in=False)
        assert dedupe.occurred_at.tzinfo is not None
        assert VIEWER_IP not in dedupe.key

    async def test_the_owner_opening_their_own_link_is_not_an_open(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc")

        kind = await record_open(
            "abc", LinkViewer(user_id=OWNER, ip=VIEWER_IP, user_agent=BROWSER_UA)
        )

        assert kind is LinkViewerKind.OWNER
        capture.assert_not_called()

    @pytest.mark.parametrize(
        "user_agent",
        [
            "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
            "facebookexternalhit/1.1 Facebot Twitterbot/1.0",
            "WhatsApp/2.23.20.0",
            "TelegramBot (like TwitterBot)",
            "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
            "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        ],
    )
    async def test_an_unfurl_bot_fetching_a_preview_is_not_an_open(self, repo, capture, user_agent):
        repo.get_by_slug.return_value = _link("abc")

        kind = await record_open("abc", _anonymous(user_agent=user_agent))

        assert kind is LinkViewerKind.UNFURL_BOT
        capture.assert_not_called()

    async def test_the_same_viewer_reopening_the_same_day_is_the_same_open(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc")

        await record_open("abc", _anonymous())
        first = _opened_dedupe(capture)
        await record_open("abc", _anonymous())

        assert _opened_dedupe(capture) == first

    async def test_another_viewer_or_another_day_is_another_open(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc")

        await record_open("abc", _anonymous())
        first = _opened_dedupe(capture)
        await record_open("abc", _anonymous(ip="203.0.113.9"))
        other_viewer = _opened_dedupe(capture)
        with patch(f"{_SVC}.datetime") as clock:
            clock.now.return_value = datetime(2030, 1, 2, 12, tzinfo=UTC)
            await record_open("abc", _anonymous())
        other_day = _opened_dedupe(capture)

        assert len({first.key, other_viewer.key, other_day.key}) == 3
        assert other_day.occurred_at != first.occurred_at

    async def test_a_signed_in_viewer_is_one_viewer_on_any_network(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc")

        await record_open(
            "abc", LinkViewer(user_id=OTHER_USER, ip=VIEWER_IP, user_agent=BROWSER_UA)
        )
        at_home = _opened_dedupe(capture)
        await record_open(
            "abc", LinkViewer(user_id=OTHER_USER, ip="203.0.113.9", user_agent="Other")
        )

        assert _opened_dedupe(capture) == at_home
        ((_, event, _), _) = capture.call_args
        assert event.viewer_signed_in is True

    async def test_a_dead_link_records_nothing(self, repo, capture):
        repo.get_by_slug.return_value = _link("abc", revoked=True)

        assert await record_open("abc", _anonymous()) is None
        capture.assert_not_called()


class TestGetPublicFile:
    async def test_the_links_own_target_names_the_file(self, repo, tmp_path):
        """The file is whatever the link's target type locates, read as its owner."""
        repo.get_by_slug.return_value = _link(
            "abc",
            target_type=ShortLinkTargetType.SESSION_ARTIFACT,
            target_id="conv-1/report.pdf",
        )
        with patch(f"{_SVC}.target_file", AsyncMock(return_value=tmp_path)) as file_lookup:
            assert await get_public_file("abc") == tmp_path
        file_lookup.assert_awaited_once_with(
            ShortLinkTargetType.SESSION_ARTIFACT, OWNER, "conv-1/report.pdf"
        )
        repo.get_by_slug.assert_awaited_once_with("abc")

    async def test_a_revoked_link_serves_no_file(self, repo):
        repo.get_by_slug.return_value = _link("abc", revoked=True)
        with patch(f"{_SVC}.target_file", AsyncMock()) as file_lookup:
            assert await get_public_file("abc") is None
        file_lookup.assert_not_awaited()


class TestOptionalShortLink:
    """GAIA attaching a link to something it hands over: never against the owner's wishes."""

    async def test_a_target_the_owner_stopped_sharing_is_never_reshared(self, repo, capture):
        """Revocation sticks: the next artifact event must not mint a fresh link."""
        repo.get_latest_for_target.return_value = _link("dead", revoked=True)

        assert await optional_short_link(OWNER, TODO, "t1") is None

        repo.get_latest_for_target.assert_awaited_once_with(OWNER, TODO, "t1")
        repo.create.assert_not_awaited()
        capture.assert_not_called()

    async def test_the_live_link_is_handed_out_again(self, repo):
        repo.get_latest_for_target.return_value = _link("live")

        url = await optional_short_link(OWNER, TODO, "t1")

        assert url is not None
        assert url.endswith("/live")
        repo.create.assert_not_awaited()

    async def test_a_never_shared_target_gets_a_fresh_link(self, repo, capture):
        repo.create.side_effect = lambda link: link

        url = await optional_short_link(OWNER, TODO, "t1")

        (stored,), _ = repo.create.await_args
        assert url is not None
        assert url.endswith(f"/{stored.slug}")
        capture.assert_called_once_with(UserId(OWNER), ShortLinkCreated(target_type=TODO.value))

    async def test_a_mongo_failure_costs_only_the_link_and_is_an_error_event(self, repo):
        repo.get_latest_for_target.side_effect = ServerSelectionTimeoutError("no primary")

        async with captured_wide_event() as event:
            assert await optional_short_link(OWNER, TODO, "t1") is None

        assert event["errors"] == [
            {
                "msg": "short_link.mint_failed",
                "user_id": OWNER,
                "target_type": TODO.value,
                "error_type": "ServerSelectionTimeoutError",
                "error": "no primary",
            }
        ]

    async def test_slug_exhaustion_costs_only_the_link(self, repo):
        repo.create.side_effect = _dup(SLUG_UNIQUE_INDEX)

        async with captured_wide_event() as event:
            assert await optional_short_link(OWNER, TODO, "t1") is None

        assert [e["msg"] for e in event["errors"]] == [
            "short_link.slug_exhausted",
            "short_link.mint_failed",
        ]

    async def test_an_unexpected_failure_still_propagates(self, repo):
        """Only the two failures the link can absorb are absorbed; a bug stays loud."""
        repo.get_latest_for_target.side_effect = RuntimeError("bug")

        with pytest.raises(RuntimeError, match="bug"):
            await optional_short_link(OWNER, TODO, "t1")


class TestStopSharing:
    async def test_the_live_link_is_revoked_and_counted(self, repo, capture):
        repo.get_live_for_target.return_value = _link("live")
        repo.revoke = AsyncMock(return_value=True)

        async with captured_wide_event() as event:
            assert await stop_sharing(OWNER, TODO, "t1") is True

        repo.get_live_for_target.assert_awaited_once_with(OWNER, TODO, "t1")
        repo.revoke.assert_awaited_once_with(OWNER, "live")
        capture.assert_called_once_with(UserId(OWNER), ShortLinkRevoked())
        assert event["short_link"] == {"slug_hash": hash_short_link_slug("live")}

    async def test_a_target_with_no_live_link_revokes_nothing(self, repo, capture):
        repo.revoke = AsyncMock()

        assert await stop_sharing(OWNER, TODO, "t1") is False

        repo.revoke.assert_not_awaited()
        capture.assert_not_called()


class TestLiveShareUrl:
    async def test_a_live_link_is_reported_as_its_url(self, repo):
        repo.get_live_for_target.return_value = _link("live1234567")

        assert (await live_share_url(OWNER, TODO, "t1") or "").endswith("/live1234567")
        repo.get_live_for_target.assert_awaited_once_with(OWNER, TODO, "t1")

    async def test_no_live_link_is_none_and_mints_nothing(self, repo, capture):
        assert await live_share_url(OWNER, TODO, "t1") is None

        repo.create.assert_not_awaited()
        capture.assert_not_called()
