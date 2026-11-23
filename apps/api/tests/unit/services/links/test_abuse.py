"""Guessing lockout, reports, suspension and takedown of heygaia.link links.

Redis is a per-test fakeredis; the repositories, analytics capture, email
sender and snapshot store are mocked at their seams. The report collection's
one-per-reporter index runs over real Mongo in tests/contracts/test_link_reports_repository.py.
"""

from collections.abc import Awaitable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, _Call, call, patch

import fakeredis.aioredis
import pytest
import time_machine

from app.config.settings import settings
from app.constants.email import SUPPORT_SENDER
from app.constants.short_links import (
    MAX_RESOLVE_MISSES,
    RESOLVE_LOCKOUT_KEY,
    RESOLVE_MISS_KEY,
    RESOLVE_MISS_LOCKOUT_SECONDS,
    RESOLVE_MISS_WINDOW_SECONDS,
    TRUSTED_REPORTER_MIN_ACCOUNT_AGE_DAYS,
)
from app.models.short_link_models import (
    LinkAccess,
    LinkSnapshot,
    RenderMode,
    ReportReason,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
    ShortLinkUpdate,
    WorkspaceFileTarget,
)
from app.models.user_models import UserDocument
from app.services.email.models import EmailMessage
from app.services.links import abuse
from app.services.support_service import SUPPORT_EMAILS
from app.utils.errors import AppError
from app.utils.log_identifiers import hash_short_link_slug
from shared.py.analytics import UserId
from shared.py.analytics.catalog.short_links import ShortLinkReported, ShortLinkTakenDown
from tests.helpers import captured_wide_event

_MODULE = "app.services.links.abuse"
OWNER = "507f1f77bcf86cd799439011"
SLUG = "abcdefghijk"
VIEWER = "203.0.113.7"


def _snapshot(render: RenderMode) -> LinkSnapshot:
    return LinkSnapshot(
        filename="r.html", mime="text/html", size_bytes=10, render=render, content_id="c" * 26
    )


def _link(**overrides: object) -> ShortLink:
    data: dict[str, object] = {
        "slug": SLUG,
        "user_id": OWNER,
        "target": WorkspaceFileTarget(
            type=ShortLinkTargetType.WORKSPACE_FILE, conversation_id="conv-1", path="r.html"
        ),
        "access": LinkAccess.PUBLIC,
    }
    data.update(overrides)
    return ShortLink.model_validate(data)


class TestGuessingLockout:
    async def test_a_locked_out_viewer_is_refused_with_429_and_another_viewer_is_not(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(RESOLVE_LOCKOUT_KEY.format(viewer=VIEWER), "1")

        with pytest.raises(AppError) as raised:
            await abuse.refuse_when_locked_out(VIEWER)

        assert (raised.value.status_code, raised.value.code) == (429, "link_lookup_locked")
        assert raised.value.message == (
            "Too many links that don't exist were opened from here. Try again in an hour."
        )
        await abuse.refuse_when_locked_out("198.51.100.1")

    async def test_misses_are_counted_by_slug_hash_within_a_window(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await abuse.record_miss(VIEWER, SLUG)
        await abuse.record_miss(VIEWER, SLUG)

        key = RESOLVE_MISS_KEY.format(viewer=VIEWER)
        members = await cast("Awaitable[set[str]]", fake_redis.smembers(key))
        assert members == {hash_short_link_slug(SLUG)}
        assert 0 < await fake_redis.ttl(key) <= RESOLVE_MISS_WINDOW_SECONDS
        assert await fake_redis.ttl(key) > RESOLVE_MISS_WINDOW_SECONDS - 5

    async def test_one_miss_past_the_limit_locks_the_viewer_out(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        for n in range(MAX_RESOLVE_MISSES):
            await abuse.record_miss(VIEWER, f"slug-{n}")
        lockout = RESOLVE_LOCKOUT_KEY.format(viewer=VIEWER)
        assert await fake_redis.exists(lockout) == 0

        async with captured_wide_event() as event:
            with pytest.raises(AppError) as raised:
                await abuse.record_miss(VIEWER, "one-too-many")

        assert raised.value.code == "link_lookup_locked"
        assert event["warnings"] == [{"msg": "short_link.lookup_locked_out"}]
        assert await fake_redis.get(lockout) == "1"
        assert await fake_redis.ttl(lockout) > RESOLVE_MISS_LOCKOUT_SECONDS - 5
        assert await fake_redis.ttl(lockout) <= RESOLVE_MISS_LOCKOUT_SECONDS
        assert await fake_redis.exists(RESOLVE_LOCKOUT_KEY.format(viewer="198.51.100.1")) == 0


@dataclass(frozen=True, slots=True)
class Seams:
    reports: MagicMock
    links: MagicMock
    users: MagicMock
    capture: MagicMock
    send_email: AsyncMock
    delete_snapshot: AsyncMock


ESTABLISHED = UserDocument(
    email="r@example.com",
    created_at=datetime.now(UTC) - timedelta(days=TRUSTED_REPORTER_MIN_ACCOUNT_AGE_DAYS + 1),
)
FRESH = UserDocument(email="new@example.com", created_at=datetime.now(UTC) - timedelta(hours=1))


@pytest.fixture
def seams() -> Iterator[Seams]:
    with (
        patch(f"{_MODULE}.link_report_repository") as reports,
        patch(f"{_MODULE}.short_link_repository") as links,
        patch(f"{_MODULE}.user_repository") as users,
        patch(f"{_MODULE}.capture") as capture,
        patch(f"{_MODULE}.send_email", AsyncMock()) as send_email,
        patch(f"{_MODULE}.delete_snapshot", AsyncMock()) as delete_snapshot,
    ):
        reports.add = AsyncMock(return_value=True)
        reports.signed_in_reporters = AsyncMock(return_value=1)
        reports.trusted_reporters = AsyncMock(return_value=1)
        users.get = AsyncMock(return_value=ESTABLISHED)
        links.update = AsyncMock()
        links.revoke = AsyncMock()
        yield Seams(reports, links, users, capture, send_email, delete_snapshot)


def _reported(signed_in: bool = True) -> _Call:
    return call(
        UserId(OWNER),
        ShortLinkReported(
            target_type="workspace_file", reason="phishing", reporter_signed_in=signed_in
        ),
    )


def _suspended() -> _Call:
    return call(
        UserId(OWNER),
        ShortLinkTakenDown(target_type="workspace_file", reason="reports_threshold"),
    )


async def _report(link: ShortLink, reporter_id: str | None = "reporter-1") -> None:
    await abuse.report(
        link, ReportReason.PHISHING, reporter_id or "address", reporter_id=reporter_id
    )


class TestReport:
    async def test_a_signed_out_report_is_recorded_and_counted_but_weighs_nothing(
        self, seams: Seams
    ) -> None:
        await _report(_link(), reporter_id=None)

        (stored,) = seams.reports.add.await_args.args
        assert (
            stored.slug,
            stored.reason,
            stored.reporter_key,
            stored.signed_in,
            stored.trusted,
        ) == (
            SLUG,
            ReportReason.PHISHING,
            "address",
            False,
            False,
        )
        assert seams.capture.call_args_list == [_reported(signed_in=False)]
        seams.reports.trusted_reporters.assert_not_awaited()
        seams.links.update.assert_not_awaited()

    @pytest.mark.parametrize(
        ("account", "trusted"),
        [(ESTABLISHED, True), (FRESH, False), (None, False), (UserDocument(), False)],
    )
    async def test_a_reporter_is_trusted_only_with_an_established_account(
        self, seams: Seams, account: UserDocument | None, trusted: bool
    ) -> None:
        seams.users.get.return_value = account

        await _report(_link())

        seams.users.get.assert_awaited_once_with("reporter-1")
        assert seams.reports.add.await_args.args[0].trusted is trusted

    async def test_a_repeat_report_from_the_same_reporter_changes_nothing(
        self, seams: Seams
    ) -> None:
        seams.reports.add.return_value = False

        await _report(_link())

        seams.capture.assert_not_called()
        seams.reports.trusted_reporters.assert_not_awaited()
        seams.links.update.assert_not_awaited()

    @pytest.mark.parametrize(
        ("snapshot", "access", "threshold"),
        [
            (_snapshot(RenderMode.FRAME_ACTIVE), LinkAccess.PUBLIC, 3),
            (_snapshot(RenderMode.DOWNLOAD), LinkAccess.UNLISTED, 3),
            (_snapshot(RenderMode.FRAME_ACTIVE), LinkAccess.OWNER, 5),
            (_snapshot(RenderMode.IMAGE), LinkAccess.PUBLIC, 5),
            (None, LinkAccess.PUBLIC, 5),
        ],
    )
    async def test_the_threshold_th_trusted_reporter_suspends_the_link(
        self,
        seams: Seams,
        snapshot: LinkSnapshot | None,
        access: LinkAccess,
        threshold: int,
    ) -> None:
        link = _link(snapshot=snapshot, access=access)
        seams.reports.trusted_reporters.return_value = threshold - 1
        await _report(link)
        seams.links.update.assert_not_awaited()

        seams.reports.trusted_reporters.return_value = threshold
        await _report(link, "reporter-2")

        seams.links.update.assert_awaited_once_with(
            SLUG, user_id=OWNER, update=ShortLinkUpdate(suspended=True)
        )
        assert seams.capture.call_args_list == [_reported(), _reported(), _suspended()]

    async def test_fresh_accounts_reaching_the_threshold_queue_one_review(
        self, seams: Seams
    ) -> None:
        seams.users.get.return_value = FRESH
        seams.reports.trusted_reporters.return_value = 0
        seams.reports.signed_in_reporters.return_value = 3

        async with captured_wide_event() as event:
            await _report(_link(snapshot=_snapshot(RenderMode.FRAME_ACTIVE)))
        seams.reports.signed_in_reporters.return_value = 4
        await _report(_link(snapshot=_snapshot(RenderMode.FRAME_ACTIVE)), "reporter-4")

        seams.links.update.assert_not_awaited()
        assert event["warnings"] == [
            {
                "msg": "short_link.review_requested",
                "user_id": OWNER,
                "target_type": "workspace_file",
                "slug_hash": hash_short_link_slug(SLUG),
                "reporters": 3,
            }
        ]
        assert {c.args[0].subject for c in seams.send_email.await_args_list} == {
            "A shared GAIA link needs review"
        }
        assert seams.send_email.await_count == len(SUPPORT_EMAILS)

    async def test_a_suspended_link_is_not_suspended_again(self, seams: Seams) -> None:
        seams.reports.trusted_reporters.return_value = 10

        await _report(_link(suspended=True))

        seams.links.update.assert_not_awaited()
        seams.send_email.assert_not_awaited()

    async def test_a_suspension_emails_every_support_inbox(self, seams: Seams) -> None:
        seams.reports.trusted_reporters.return_value = 5

        async with captured_wide_event() as event:
            await _report(_link())

        assert event["errors"] == [
            {
                "msg": "short_link.suspended",
                "user_id": OWNER,
                "target_type": "workspace_file",
                "slug_hash": hash_short_link_slug(SLUG),
                "reporters": 5,
            }
        ]
        html = (
            f"<p>{settings.SHORTLINK_BASE_URL}/{SLUG} was suspended after 5 reports.</p>"
            f"<p>Owner: {OWNER}. Type: workspace_file.</p>"
            "<p>Restore it with <code>apps/api/scripts/link_takedown.py --slug SLUG --restore</code>, "
            "or take it down with <code>--reason admin</code>.</p>"
        )
        assert seams.send_email.await_args_list == [
            call(
                EmailMessage(
                    sender=SUPPORT_SENDER,
                    to=[address],
                    subject="A shared GAIA link was suspended",
                    html=html,
                )
            )
            for address in SUPPORT_EMAILS
        ]

    async def test_a_self_hosted_suspension_emails_no_one(
        self, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        seams.reports.trusted_reporters.return_value = 5

        await _report(_link())

        seams.links.update.assert_awaited_once()
        seams.send_email.assert_not_awaited()


class TestTakedown:
    async def test_a_takedown_revokes_deletes_the_file_and_is_counted(self, seams: Seams) -> None:
        snapshot = _snapshot(RenderMode.FRAME_ACTIVE)

        await abuse.take_down(_link(snapshot=snapshot))

        seams.links.revoke.assert_awaited_once_with(OWNER, SLUG, RevokeReason.TAKEDOWN)
        seams.delete_snapshot.assert_awaited_once_with(OWNER, snapshot)
        assert seams.capture.call_args_list == [
            call(UserId(OWNER), ShortLinkTakenDown(target_type="workspace_file", reason="admin"))
        ]

    async def test_a_link_without_a_file_has_nothing_to_delete(self, seams: Seams) -> None:
        await abuse.take_down(_link())

        seams.links.revoke.assert_awaited_once()
        seams.delete_snapshot.assert_not_awaited()

    async def test_restoring_lifts_the_suspension(self, seams: Seams) -> None:
        await abuse.restore(_link(suspended=True))

        seams.links.update.assert_awaited_once_with(
            SLUG, user_id=OWNER, update=ShortLinkUpdate(suspended=False)
        )


class TestReportCounts:
    async def test_an_account_exactly_the_minimum_age_is_trusted(self, seams: Seams) -> None:
        now = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
        seams.users.get.return_value = UserDocument(
            created_at=now - timedelta(days=TRUSTED_REPORTER_MIN_ACCOUNT_AGE_DAYS)
        )
        with time_machine.travel(now, tick=False):
            await _report(_link())
        assert seams.reports.add.await_args.args[0].trusted is True

    async def test_each_count_is_read_for_the_reported_link(self, seams: Seams) -> None:
        seams.users.get.return_value = FRESH
        seams.reports.trusted_reporters.return_value = 0

        await _report(_link())

        seams.reports.trusted_reporters.assert_awaited_once_with(SLUG)
        seams.reports.signed_in_reporters.assert_awaited_once_with(SLUG)

    async def test_a_review_email_says_the_link_is_still_live(self, seams: Seams) -> None:
        seams.users.get.return_value = FRESH
        seams.reports.trusted_reporters.return_value = 0
        seams.reports.signed_in_reporters.return_value = 5

        await _report(_link())

        html = seams.send_email.await_args.args[0].html
        assert html.startswith(
            f"<p>{settings.SHORTLINK_BASE_URL}/{SLUG} was reported by 5 accounts too new "
            "to suspend it; it is still live.</p>"
        )
