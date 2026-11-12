"""The mint loop's branches: slug collisions, losing a concurrent mint, exhaustion, and GAIA-attached failures.

The repository is mocked at the seam; the unique indexes these branches race
against are enforced for real in tests/contracts/test_short_links_repository.py,
and the full share/open/revoke flow runs over real Mongo in
tests/integration/real/test_links_real.py.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import re
from unittest.mock import AsyncMock, MagicMock, call, patch

from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import pytest
import time_machine

from app.config.settings import settings
from app.db.repositories.short_links import LIVE_TARGET_UNIQUE_INDEX, SLUG_UNIQUE_INDEX
from app.models.short_link_models import (
    LinkAccess,
    LinkContent,
    LinkEnvelope,
    LinkSettings,
    LinkSettingsUpdate,
    LinkSnapshot,
    LinkViewer,
    PublicTodoDeliverable,
    PublishRejection,
    RenderMode,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
    ShortLinkUpdate,
)
from app.models.user_models import UserDocument
from app.services.analytics_service import analytics_day_start
from app.services.links.errors import LinkDeniedError, LinkTargetNotFoundError
from app.services.links.registry import REGISTRY
from app.services.links.service import (
    MAX_SLUG_ATTEMPTS,
    ShortLinkExhaustedError,
    link_response,
    live_share_link,
    optional_short_link,
    resolve,
    rotate,
    share,
    update_settings,
)
from app.services.links.spec import SnapshotSource
from app.utils.errors import AppError
from app.utils.log_identifiers import hash_link_viewer, hash_short_link_slug
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.short_links import (
    ShortLinkAccessChanged,
    ShortLinkCreated,
    ShortLinkDenied,
    ShortLinkRotated,
)
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
            AppError(message="storage down", status_code=503),
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


SESSION = ShortLinkTargetType.SESSION_ARTIFACT
FILE_ID = "conv-1/q3.html"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
SOURCE = SnapshotSource(
    filename="q3.html", declared_mime="text/html", size_bytes=11, data=b"<h1>Q3</h1>"
)
VIEW = PublicTodoDeliverable(
    target_type=ShortLinkTargetType.TODO_DELIVERABLE,
    title="Q3 plan",
    completed=True,
    content="Ship it",
)
IP, UA = "203.0.113.9", "Mozilla/5.0"
RECIPIENT = LinkViewer(user_id=None, email=None, ip=IP, user_agent=UA)
AS_OWNER = LinkViewer(user_id=OWNER, email=None, ip=IP, user_agent=UA)


def _snap(content_id: str | None, **overrides: object) -> LinkSnapshot:
    data: dict[str, object] = {
        "filename": "q3.html",
        "mime": "image/png",
        "size_bytes": 11,
        "render": RenderMode.IMAGE,
        "content_id": content_id,
    }
    data.update(overrides)
    return LinkSnapshot.model_validate(data)


OLD = _snap("o" * 26)
FRESH = _snap("f" * 26)


@dataclass
class Specs:
    todo_project: AsyncMock
    file_project: AsyncMock
    file_source: AsyncMock


@dataclass
class Store:
    links: MagicMock
    publish: AsyncMock
    delete_snapshot: AsyncMock


@pytest.fixture
def specs() -> Iterator[Specs]:
    fakes = Specs(
        todo_project=AsyncMock(return_value=VIEW),
        file_project=AsyncMock(return_value=VIEW),
        file_source=AsyncMock(return_value=SOURCE),
    )
    registry = {
        TODO: replace(REGISTRY[TODO], project=fakes.todo_project),
        SESSION: replace(REGISTRY[SESSION], project=fakes.file_project, source=fakes.file_source),
    }
    with patch(f"{_SVC}.REGISTRY", registry):
        yield fakes


@pytest.fixture
def store(specs: Specs) -> Iterator[Store]:
    """Patch the link collection and the content store at their seams; service.py's logic runs for real."""
    with (
        patch(f"{_SVC}.short_link_repository") as links,
        patch(f"{_SVC}.publish", AsyncMock(return_value=FRESH)) as publish_,
        patch(f"{_SVC}.delete_snapshot", AsyncMock()) as delete_,
    ):
        links.get_live_for_target = AsyncMock(return_value=None)
        links.get_latest_for_target = AsyncMock(return_value=None)
        links.get_by_slug = AsyncMock(return_value=None)
        links.create = AsyncMock(side_effect=lambda link: link)
        links.revoke = AsyncMock(return_value=None)
        links.update_live = AsyncMock(return_value=None)
        links.live_pins_content = AsyncMock(return_value=False)
        yield Store(links=links, publish=publish_, delete_snapshot=delete_)


@pytest.fixture
def frozen() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def workos_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")


@pytest.fixture
def local_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "AUTH_MODE", "local")


@pytest.fixture
def users() -> Iterator[AsyncMock]:
    accounts = {
        "ana@x.com": [UserDocument(id="u-ana", email="ana@x.com")],
        "bo@x.com": [UserDocument(id="u-bo", email="bo@x.com")],
        "twin@x.com": [
            UserDocument(id="u-twin1", email="twin@x.com"),
            UserDocument(id="u-twin2", email="TWIN@x.com"),
        ],
    }

    async def _find(email: str) -> list[UserDocument]:
        return accounts.get(email, [])

    with patch(f"{_SVC}.user_repository") as repo:
        repo.find_by_email_ignoring_case = AsyncMock(side_effect=_find)
        yield repo.find_by_email_ignoring_case


def _stored(store: Store) -> ShortLink:
    (stored,), _ = store.links.create.await_args
    assert isinstance(stored, ShortLink)
    return stored


def _url(slug: str) -> str:
    return f"{settings.SHORTLINK_BASE_URL}/{slug}"


def _written(store: Store) -> tuple[str, dict[str, object]]:
    """Return the slug and the $set fields update_live writes: only what the update set."""
    (user_id, slug, update), _ = store.links.update_live.await_args
    assert user_id == OWNER
    return slug, update.model_dump(exclude_unset=True)


def _denied_dedupe(slug: str, viewer_key: str, reason: str) -> Dedupe:
    return Dedupe(
        key=f"{hash_short_link_slug(slug)}:{viewer_key}:{reason}:2026-11-13",
        occurred_at=analytics_day_start(NOW),
    )


class TestGrantees:
    async def test_off_local_auth_grantees_stay_emails_and_are_never_looked_up(
        self, store: Store, users: AsyncMock, workos_auth: None
    ) -> None:
        await share(
            OWNER, TODO, "t1", LinkSettings(access=LinkAccess.PEOPLE, grantees=["ana@x.com"])
        )

        stored = _stored(store)
        assert (stored.grantees, stored.grantee_ids) == (["ana@x.com"], [])
        users.assert_not_awaited()

    async def test_on_local_auth_each_grantee_resolves_to_their_one_account(
        self, store: Store, users: AsyncMock, local_auth: None
    ) -> None:
        grantees = ["ana@x.com", "bo@x.com"]

        await share(OWNER, TODO, "t1", LinkSettings(access=LinkAccess.PEOPLE, grantees=grantees))

        stored = _stored(store)
        assert (stored.grantees, stored.grantee_ids) == (grantees, ["u-ana", "u-bo"])
        assert users.await_args_list == [call("ana@x.com"), call("bo@x.com")]

    async def test_a_grantee_with_no_or_two_accounts_is_refused_before_anything_publishes(
        self, store: Store, users: AsyncMock, local_auth: None
    ) -> None:
        grantees = ["ana@x.com", "nobody@x.com", "twin@x.com"]

        with pytest.raises(AppError) as raised:
            await share(OWNER, SESSION, FILE_ID, LinkSettings(grantees=grantees))

        error = raised.value
        assert (error.message, error.fix, error.status_code, error.code, error.public) == (
            "Some of these people have no account on this GAIA",
            "Add them after they have joined, or share with anyone who has the link",
            422,
            "link_grantee_not_a_member",
            {"missing": ["nobody@x.com", "twin@x.com"]},
        )
        store.publish.assert_not_awaited()
        store.links.create.assert_not_awaited()


class TestMintSnapshot:
    async def test_a_file_link_pins_the_owners_file_as_published_now(
        self, store: Store, specs: Specs
    ) -> None:
        await share(OWNER, SESSION, FILE_ID, LinkSettings())

        specs.file_source.assert_awaited_once_with(OWNER, FILE_ID)
        store.publish.assert_awaited_once_with(OWNER, SESSION, SOURCE)
        assert _stored(store).snapshot == FRESH

    async def test_a_file_gone_before_the_mint_is_not_found(
        self, store: Store, specs: Specs
    ) -> None:
        specs.file_source.return_value = None

        with pytest.raises(LinkTargetNotFoundError):
            await share(OWNER, SESSION, FILE_ID, LinkSettings())

        store.publish.assert_not_awaited()
        store.links.create.assert_not_awaited()

    async def test_a_non_file_target_is_checked_to_exist_and_pins_nothing(
        self, store: Store, specs: Specs
    ) -> None:
        await share(OWNER, TODO, "t1", LinkSettings())

        specs.todo_project.assert_awaited_once_with(OWNER, "t1", None)
        assert _stored(store).snapshot is None

    async def test_a_non_file_target_the_owner_lacks_is_not_found(
        self, store: Store, specs: Specs
    ) -> None:
        specs.todo_project.return_value = None

        with pytest.raises(LinkTargetNotFoundError):
            await share(OWNER, TODO, "t1", LinkSettings())

        store.links.create.assert_not_awaited()


class TestMint:
    async def test_the_link_stores_exactly_the_requested_settings(
        self, store: Store, frozen: None, workos_auth: None
    ) -> None:
        expiry = NOW + timedelta(days=1)
        requested = LinkSettings(
            access=LinkAccess.PUBLIC, grantees=["ana@x.com"], expires_at=expiry
        )

        with patch(f"{_SVC}.capture") as capture:
            minted = await share(OWNER, TODO, "t1", requested)

        stored = _stored(store)
        assert (stored.access, stored.grantees, stored.expires_at) == (
            LinkAccess.PUBLIC,
            ["ana@x.com"],
            expiry,
        )
        assert minted == stored
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkCreated(
                target_type=TODO.value, access="public", origin="owner_share", has_expiry=True
            ),
        )

    async def test_an_insert_failure_releases_the_published_snapshot_and_reraises(
        self, store: Store
    ) -> None:
        store.links.create.side_effect = ServerSelectionTimeoutError("no primary")

        with pytest.raises(ServerSelectionTimeoutError):
            await share(OWNER, SESSION, FILE_ID, LinkSettings())

        store.links.live_pins_content.assert_awaited_once_with(FRESH.content_id)
        store.delete_snapshot.assert_awaited_once_with(OWNER, FRESH)

    async def test_bytes_another_live_link_still_pins_are_kept(self, store: Store) -> None:
        store.links.create.side_effect = ServerSelectionTimeoutError("no primary")
        store.links.live_pins_content.return_value = True

        with pytest.raises(ServerSelectionTimeoutError):
            await share(OWNER, SESSION, FILE_ID, LinkSettings())

        store.delete_snapshot.assert_not_awaited()

    async def test_a_snapshot_with_no_stored_bytes_has_nothing_to_release(
        self, store: Store
    ) -> None:
        store.publish.return_value = _snap(None)
        store.links.create.side_effect = ServerSelectionTimeoutError("no primary")

        with pytest.raises(ServerSelectionTimeoutError):
            await share(OWNER, SESSION, FILE_ID, LinkSettings())

        store.links.live_pins_content.assert_not_awaited()
        store.delete_snapshot.assert_not_awaited()

    async def test_losing_a_concurrent_mint_releases_the_snapshot_it_published(
        self, store: Store
    ) -> None:
        winner = _link("winner", target_type=SESSION, target_id=FILE_ID)
        store.links.get_live_for_target.side_effect = [None, winner]
        store.links.create.side_effect = _dup(LIVE_TARGET_UNIQUE_INDEX)

        assert await share(OWNER, SESSION, FILE_ID, LinkSettings()) is winner

        store.delete_snapshot.assert_awaited_once_with(OWNER, FRESH)
        assert store.links.get_live_for_target.await_args_list == [
            call(OWNER, SESSION, FILE_ID),
            call(OWNER, SESSION, FILE_ID),
        ]


class TestLiveLink:
    async def test_an_unexpired_live_link_is_handed_back_untouched(
        self, store: Store, frozen: None
    ) -> None:
        live = _link("live1", expires_at=NOW + timedelta(seconds=1))
        store.links.get_live_for_target.return_value = live

        assert await live_share_link(OWNER, TODO, "t1") is live

        store.links.get_live_for_target.assert_awaited_once_with(OWNER, TODO, "t1")
        store.links.revoke.assert_not_awaited()

    async def test_a_link_past_its_expiry_is_revoked_and_its_bytes_released(
        self, store: Store, frozen: None
    ) -> None:
        live = _link("old1", target_type=SESSION, target_id=FILE_ID, expires_at=NOW, snapshot=OLD)
        store.links.get_live_for_target.return_value = live

        assert await live_share_link(OWNER, SESSION, FILE_ID) is None

        store.links.revoke.assert_awaited_once_with(OWNER, "old1", RevokeReason.EXPIRED)
        store.delete_snapshot.assert_awaited_once_with(OWNER, OLD)

    async def test_sharing_a_target_whose_link_expired_mints_a_fresh_one(
        self, store: Store, frozen: None
    ) -> None:
        store.links.get_live_for_target.return_value = _link("old1", expires_at=NOW)

        minted = await share(OWNER, TODO, "t1", LinkSettings())

        assert SLUG_SHAPE.fullmatch(minted.slug)
        store.links.create.assert_awaited_once()


class TestGaiaAttachedSharingRules:
    @pytest.mark.parametrize(
        "latest",
        [
            {"revoked": True, "revoked_reason": RevokeReason.OWNER},
            {"revoked": True, "revoked_reason": None},
            {"revoked": True, "revoked_reason": RevokeReason.EXPIRED},
            {"revoked": True, "revoked_reason": RevokeReason.TAKEDOWN},
            {"suspended": True},
            {"expires_at": NOW},
        ],
    )
    async def test_sharing_the_owner_turned_off_stays_off(
        self, store: Store, frozen: None, latest: dict[str, object]
    ) -> None:
        store.links.get_latest_for_target.return_value = _link("old1", **latest)

        assert await optional_short_link(OWNER, TODO, "t1") is None

        store.links.create.assert_not_awaited()

    @pytest.mark.parametrize("reason", [RevokeReason.ROTATED, RevokeReason.TARGET_DELETED])
    async def test_a_link_gaia_retired_does_not_stop_a_fresh_attachment(
        self, store: Store, frozen: None, reason: RevokeReason
    ) -> None:
        store.links.get_latest_for_target.return_value = _link(
            "old1", revoked=True, revoked_reason=reason
        )

        url = await optional_short_link(OWNER, TODO, "t1")

        assert url == _url(_stored(store).slug)
        store.links.get_latest_for_target.assert_awaited_once_with(OWNER, TODO, "t1")

    async def test_a_live_link_is_attached_at_its_own_url(self, store: Store, frozen: None) -> None:
        store.links.get_latest_for_target.return_value = _link("live1")

        assert await optional_short_link(OWNER, TODO, "t1") == _url("live1")
        store.links.create.assert_not_awaited()

    async def test_a_failed_mint_logs_what_failed_and_where(self, store: Store) -> None:
        store.links.get_latest_for_target.side_effect = AppError(message="storage down")

        async with captured_wide_event() as event:
            assert await optional_short_link(OWNER, TODO, "t1") is None

        assert event["errors"] == [
            {
                "msg": "short_link.mint_failed",
                "user_id": OWNER,
                "target_type": TODO.value,
                "error_type": "AppError",
                "error": "storage down",
            }
        ]


class TestRefreshOnAttach:
    async def _attach(self, store: Store, link: ShortLink) -> str | None:
        store.links.get_latest_for_target.return_value = link
        return await optional_short_link(OWNER, SESSION, FILE_ID)

    async def test_an_unchanged_file_keeps_its_snapshot(self, store: Store, frozen: None) -> None:
        assert SOURCE.data is not None
        pinned = _snap("o" * 26, digest=hashlib.sha256(SOURCE.data).hexdigest())
        link = _link("live1", target_type=SESSION, target_id=FILE_ID, snapshot=pinned)

        assert await self._attach(store, link) == _url("live1")

        store.publish.assert_not_awaited()
        store.links.update_live.assert_not_awaited()

    async def test_a_changed_file_moves_the_link_on_and_releases_the_old_bytes(
        self, store: Store, specs: Specs, frozen: None
    ) -> None:
        link = _link("live1", target_type=SESSION, target_id=FILE_ID, snapshot=OLD)
        store.links.update_live.return_value = link.model_copy(update={"snapshot": FRESH})

        assert await self._attach(store, link) == _url("live1")

        specs.file_source.assert_awaited_once_with(OWNER, FILE_ID)
        store.publish.assert_awaited_once_with(OWNER, SESSION, SOURCE)
        store.links.update_live.assert_awaited_once_with(
            OWNER, "live1", ShortLinkUpdate(snapshot=FRESH)
        )
        store.delete_snapshot.assert_awaited_once_with(OWNER, OLD)

    async def test_a_link_that_died_meanwhile_keeps_its_bytes_and_the_fresh_ones_go(
        self, store: Store, frozen: None
    ) -> None:
        link = _link("live1", target_type=SESSION, target_id=FILE_ID, snapshot=OLD)
        store.links.update_live.return_value = None

        await self._attach(store, link)

        store.delete_snapshot.assert_awaited_once_with(OWNER, FRESH)

    async def test_a_file_deleted_since_keeps_the_pinned_snapshot(
        self, store: Store, specs: Specs, frozen: None
    ) -> None:
        specs.file_source.return_value = None
        link = _link("live1", target_type=SESSION, target_id=FILE_ID, snapshot=OLD)

        assert await self._attach(store, link) == _url("live1")

        store.publish.assert_not_awaited()


class TestUpdateSettings:
    @pytest.mark.parametrize(
        "found",
        [
            None,
            _link("s1", user_id="507f1f77bcf86cd799439099"),
            _link("s1", revoked=True, revoked_reason=RevokeReason.OWNER),
            _link("s1", expires_at=NOW),
        ],
    )
    async def test_only_the_owners_live_link_can_change(
        self, store: Store, frozen: None, found: ShortLink | None
    ) -> None:
        store.links.get_by_slug.return_value = found

        with pytest.raises(LinkTargetNotFoundError) as raised:
            await update_settings(OWNER, "s1", LinkSettingsUpdate(access=LinkAccess.PUBLIC))

        assert raised.value.message == "Link not found"
        store.links.get_by_slug.assert_awaited_once_with("s1")
        store.links.update_live.assert_not_awaited()

    @pytest.mark.parametrize("expiry", [NOW, NOW - timedelta(seconds=1)])
    async def test_an_expiry_not_in_the_future_is_refused(
        self, store: Store, frozen: None, expiry: datetime
    ) -> None:
        store.links.get_by_slug.return_value = _link("s1")

        with pytest.raises(AppError) as raised:
            await update_settings(OWNER, "s1", LinkSettingsUpdate(expires_at=expiry))

        error = raised.value
        assert (error.message, error.fix, error.status_code, error.code) == (
            "That expiry is already in the past",
            "Pick a time from now on, or no expiry",
            422,
            "link_expiry_in_past",
        )
        store.links.update_live.assert_not_awaited()

    async def test_an_empty_change_is_refused(self, store: Store, frozen: None) -> None:
        store.links.get_by_slug.return_value = _link("s1")

        with pytest.raises(AppError) as raised:
            await update_settings(OWNER, "s1", LinkSettingsUpdate())

        error = raised.value
        assert (error.message, error.fix, error.status_code, error.code) == (
            "Nothing to change",
            "",
            422,
            "link_settings_empty",
        )

    async def test_a_new_expiry_is_set_alone_and_counts_no_access_change(
        self, store: Store, frozen: None
    ) -> None:
        link = _link("s1")
        expiry = NOW + timedelta(hours=1)
        updated = link.model_copy(update={"expires_at": expiry})
        store.links.get_by_slug.return_value = link
        store.links.update_live.return_value = updated

        with patch(f"{_SVC}.capture") as capture:
            result = await update_settings(OWNER, "s1", LinkSettingsUpdate(expires_at=expiry))

        assert result is updated
        assert _written(store) == ("s1", {"expires_at": expiry})
        capture.assert_not_called()

    async def test_widening_access_writes_only_access_and_is_counted(
        self, store: Store, frozen: None
    ) -> None:
        link = _link("s1", expires_at=NOW + timedelta(days=1))
        store.links.get_by_slug.return_value = link
        store.links.update_live.return_value = link.model_copy(update={"access": LinkAccess.PUBLIC})

        with patch(f"{_SVC}.capture") as capture:
            await update_settings(OWNER, "s1", LinkSettingsUpdate(access=LinkAccess.PUBLIC))

        assert _written(store) == ("s1", {"access": LinkAccess.PUBLIC})
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkAccessChanged(
                target_type=TODO.value, from_access="unlisted", to_access="public", grantee_count=0
            ),
        )

    async def test_new_grantees_resolve_to_accounts_and_are_counted(
        self, store: Store, users: AsyncMock, local_auth: None, frozen: None
    ) -> None:
        link = _link("s1", access=LinkAccess.PEOPLE)
        store.links.get_by_slug.return_value = link
        store.links.update_live.return_value = link.model_copy(
            update={"grantees": ["ana@x.com"], "grantee_ids": ["u-ana"]}
        )

        with patch(f"{_SVC}.capture") as capture:
            await update_settings(OWNER, "s1", LinkSettingsUpdate(grantees=["ana@x.com"]))

        store.links.update_live.assert_awaited_once_with(
            OWNER, "s1", ShortLinkUpdate(grantees=["ana@x.com"], grantee_ids=["u-ana"])
        )
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkAccessChanged(
                target_type=TODO.value, from_access="people", to_access="people", grantee_count=1
            ),
        )

    async def test_null_grantees_clears_them(
        self, store: Store, workos_auth: None, frozen: None
    ) -> None:
        link = _link("s1", access=LinkAccess.PEOPLE, grantees=["ana@x.com"])
        store.links.get_by_slug.return_value = link
        store.links.update_live.return_value = link.model_copy(update={"grantees": []})

        with patch(f"{_SVC}.capture"):
            await update_settings(OWNER, "s1", LinkSettingsUpdate(grantees=None))

        store.links.update_live.assert_awaited_once_with(
            OWNER, "s1", ShortLinkUpdate(grantees=[], grantee_ids=[])
        )

    async def test_a_link_that_died_mid_change_is_not_found(
        self, store: Store, frozen: None
    ) -> None:
        store.links.get_by_slug.return_value = _link("s1")
        store.links.update_live.return_value = None

        with pytest.raises(LinkTargetNotFoundError) as raised:
            await update_settings(OWNER, "s1", LinkSettingsUpdate(access=LinkAccess.PUBLIC))

        assert raised.value.message == "Link not found"


class TestRotate:
    async def test_the_new_url_carries_the_revoked_docs_settings_and_file(
        self, store: Store, frozen: None
    ) -> None:
        read = _link(
            "s1",
            id="doc1",
            access=LinkAccess.PEOPLE,
            grantees=["ana@x.com"],
            target_type=SESSION,
            target_id=FILE_ID,
            snapshot=OLD,
            created_at=NOW - timedelta(days=3),
        )
        revoked = read.model_copy(
            update={
                "snapshot": FRESH,
                "updated_at": NOW,
                "revoked": True,
                "revoked_at": NOW,
                "revoked_reason": RevokeReason.ROTATED,
            }
        )
        store.links.get_by_slug.return_value = read
        store.links.revoke.return_value = revoked

        with patch(f"{_SVC}.capture") as capture:
            minted = await rotate(OWNER, "s1")

        store.links.get_by_slug.assert_awaited_once_with("s1")
        store.links.revoke.assert_awaited_once_with(OWNER, "s1", RevokeReason.ROTATED)
        stored = _stored(store)
        assert minted is stored
        assert SLUG_SHAPE.fullmatch(stored.slug)
        assert stored.model_dump(exclude={"slug"}) == {
            **revoked.model_dump(exclude={"slug"}),
            "id": "",
            "created_at": NOW,
            "updated_at": None,
            "revoked": False,
            "revoked_at": None,
            "revoked_reason": None,
        }
        capture.assert_called_once_with(
            UserId(OWNER), ShortLinkRotated(target_type=SESSION.value, access="people")
        )

    async def test_a_link_revoked_before_the_rotation_is_not_found(
        self, store: Store, frozen: None
    ) -> None:
        store.links.get_by_slug.return_value = _link("s1")
        store.links.revoke.return_value = None

        with pytest.raises(LinkTargetNotFoundError) as raised:
            await rotate(OWNER, "s1")

        assert raised.value.message == "Link not found"
        store.links.create.assert_not_awaited()

    async def test_a_share_racing_the_rotation_is_a_conflict(
        self, store: Store, frozen: None
    ) -> None:
        link = _link("s1")
        store.links.get_by_slug.return_value = link
        store.links.revoke.return_value = link.model_copy(update={"revoked": True})
        store.links.create.side_effect = _dup(LIVE_TARGET_UNIQUE_INDEX)

        with pytest.raises(AppError) as raised:
            await rotate(OWNER, "s1")

        error = raised.value
        assert (error.message, error.fix, error.status_code, error.code) == (
            "This was shared again while the link was being replaced",
            "Reload to see its current link",
            409,
            "link_rotate_conflict",
        )


class TestResolve:
    async def test_an_unknown_slug_is_not_found_and_counted_for_no_one(self, frozen: None) -> None:
        with patch(f"{_SVC}.capture") as capture, pytest.raises(LinkDeniedError) as raised:
            await resolve(None, RECIPIENT)

        assert (raised.value.code, raised.value.status_code) == ("link_not_found", 404)
        capture.assert_not_called()

    async def test_a_dead_link_is_denied_and_counted_once_a_day_per_viewer(
        self, specs: Specs, frozen: None
    ) -> None:
        link = _link("s1", revoked=True, revoked_reason=RevokeReason.OWNER)
        viewer = LinkViewer(user_id=None, email=None, ip=IP, user_agent=UA, signed_in_as="me@x.com")

        with patch(f"{_SVC}.capture") as capture, pytest.raises(LinkDeniedError) as raised:
            await resolve(link, viewer)

        assert (raised.value.code, raised.value.public) == ("link_revoked", {})
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkDenied(target_type=TODO.value, reason="revoked"),
            _denied_dedupe("s1", hash_link_viewer(IP, UA), "revoked"),
        )
        specs.todo_project.assert_not_awaited()

    async def test_a_signed_in_viewer_not_granted_is_told_who_they_are_signed_in_as(
        self, frozen: None
    ) -> None:
        link = _link("s1", access=LinkAccess.PEOPLE, grantees=["ana@x.com"])
        viewer = LinkViewer(
            user_id="u-eve", email=None, ip=IP, user_agent=UA, signed_in_as="eve@x.com"
        )

        with patch(f"{_SVC}.capture") as capture, pytest.raises(LinkDeniedError) as raised:
            await resolve(link, viewer)

        assert (raised.value.code, raised.value.public) == (
            "link_forbidden",
            {"signed_in_as": "eve@x.com"},
        )
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkDenied(target_type=TODO.value, reason="forbidden"),
            _denied_dedupe("s1", "u-eve", "forbidden"),
        )

    async def test_a_target_the_owner_deleted_is_denied_as_deleted(
        self, specs: Specs, frozen: None
    ) -> None:
        specs.todo_project.return_value = None

        with patch(f"{_SVC}.capture") as capture, pytest.raises(LinkDeniedError) as raised:
            await resolve(_link("s1"), RECIPIENT)

        assert raised.value.code == "link_target_deleted"
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkDenied(target_type=TODO.value, reason="target_deleted"),
            _denied_dedupe("s1", hash_link_viewer(IP, UA), "target_deleted"),
        )

    async def test_a_recipient_sees_the_view_and_none_of_the_owners_controls(
        self, specs: Specs, frozen: None
    ) -> None:
        envelope = await resolve(_link("s1", expires_at=NOW + timedelta(hours=1)), RECIPIENT)

        assert envelope == LinkEnvelope(
            access=LinkAccess.UNLISTED,
            target_type=TODO,
            view=VIEW,
            content=None,
            downloadable=False,
            is_owner=False,
            owner_target_id=None,
        )
        specs.todo_project.assert_awaited_once_with(OWNER, "t1", None)

    async def test_the_owner_opens_a_file_framed_with_their_share_controls(
        self, specs: Specs, frozen: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", "https://{content_id}.u.test")
        monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", "k" * 32)
        link = _link("s1", target_type=SESSION, target_id=FILE_ID, snapshot=FRESH)

        envelope = await resolve(link, AS_OWNER)

        assert envelope == LinkEnvelope(
            access=LinkAccess.UNLISTED,
            target_type=SESSION,
            view=VIEW,
            content=LinkContent(
                content_id="f" * 26, mime="image/png", size_bytes=11, render=RenderMode.IMAGE
            ),
            downloadable=True,
            is_owner=True,
            owner_target_id=FILE_ID,
        )
        specs.file_project.assert_awaited_once_with(OWNER, FILE_ID, FRESH)

    async def test_bytes_capped_below_the_links_access_are_withheld_from_the_view(
        self, specs: Specs, frozen: None
    ) -> None:
        capped = _snap("f" * 26, max_access=LinkAccess.UNLISTED)
        link = _link(
            "s1", access=LinkAccess.PUBLIC, target_type=SESSION, target_id=FILE_ID, snapshot=capped
        )

        envelope = await resolve(link, RECIPIENT)

        specs.file_project.assert_awaited_once_with(
            OWNER, FILE_ID, capped.model_copy(update={"content_id": None})
        )
        assert (envelope.content, envelope.downloadable) == (None, False)


class TestLinkResponse:
    def test_a_restricted_file_names_the_widest_level_it_may_be_served_at(self) -> None:
        expires = NOW + timedelta(days=1)
        link = _link(
            "abcdefghijk",
            access=LinkAccess.PEOPLE,
            grantees=["a@example.com"],
            expires_at=expires,
            snapshot=_snap(
                "c" * 26,
                max_access=LinkAccess.PEOPLE,
                restricted_by=PublishRejection.RESTRICTED_TYPE,
            ),
        )

        assert link_response(link).model_dump() == {
            "url": f"{settings.SHORTLINK_BASE_URL}/abcdefghijk",
            "slug": "abcdefghijk",
            "access": LinkAccess.PEOPLE,
            "grantees": ["a@example.com"],
            "expires_at": expires,
            "content_max_access": LinkAccess.PEOPLE,
        }

    @pytest.mark.parametrize(
        "snapshot", [None, _snap("c" * 26, max_access=LinkAccess.PEOPLE)], ids=["none", "open"]
    )
    def test_a_link_whose_file_nothing_narrowed_names_no_level(
        self, snapshot: LinkSnapshot | None
    ) -> None:
        assert link_response(_link("abcdefghijk", snapshot=snapshot)).content_max_access is None
