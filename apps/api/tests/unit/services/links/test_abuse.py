"""Guessing lockout, reports, suspension and takedown of heygaia.link links.

Redis is a per-test fakeredis; the repositories, analytics capture, email
sender and snapshot store are mocked at their seams. The report collection's
one-per-reporter index runs over real Mongo in tests/contracts/test_link_reports_repository.py.
"""

from collections.abc import Awaitable, Iterator
from dataclasses import dataclass
from typing import cast
from unittest.mock import AsyncMock, MagicMock, _Call, call, patch

import fakeredis.aioredis
import pytest

from app.config.settings import settings
from app.constants.email import SUPPORT_SENDER
from app.constants.short_links import (
    MAX_RESOLVE_MISSES,
    RESOLVE_LOCKOUT_KEY,
    RESOLVE_MISS_KEY,
    RESOLVE_MISS_LOCKOUT_SECONDS,
    RESOLVE_MISS_WINDOW_SECONDS,
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
)
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
        "target_type": ShortLinkTargetType.SESSION_ARTIFACT,
        "target_id": "conv-1/r.html",
        "access": LinkAccess.PUBLIC,
    }
    data.update(overrides)
    return ShortLink.model_validate(data)


class TestGuessingLockout:
    async def test_a_viewer_with_no_lockout_passes(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await abuse.refuse_when_locked_out(VIEWER)

    async def test_a_locked_out_viewer_is_refused_with_429(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(RESOLVE_LOCKOUT_KEY.format(viewer=VIEWER), "1")

        with pytest.raises(AppError) as raised:
            await abuse.refuse_when_locked_out(VIEWER)

        assert (raised.value.status_code, raised.value.code) == (429, "link_lookup_locked")
        assert raised.value.message == "Too many links that don't exist were opened from here"
        assert raised.value.fix == "Try again in an hour"
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
    capture: MagicMock
    send_email: AsyncMock
    delete_snapshot: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    with (
        patch(f"{_MODULE}.link_report_repository") as reports,
        patch(f"{_MODULE}.short_link_repository") as links,
        patch(f"{_MODULE}.capture") as capture,
        patch(f"{_MODULE}.send_email", AsyncMock()) as send_email,
        patch(f"{_MODULE}.delete_snapshot", AsyncMock()) as delete_snapshot,
    ):
        reports.add = AsyncMock(return_value=True)
        reports.signed_in_reporters = AsyncMock(return_value=1)
        links.update = AsyncMock()
        links.revoke = AsyncMock()
        yield Seams(reports, links, capture, send_email, delete_snapshot)


def _reported(signed_in: bool = True) -> _Call:
    return call(
        UserId(OWNER),
        ShortLinkReported(
            target_type="session_artifact", reason="phishing", reporter_signed_in=signed_in
        ),
    )


def _suspended() -> _Call:
    return call(
        UserId(OWNER),
        ShortLinkTakenDown(target_type="session_artifact", reason="reports_threshold"),
    )


class TestReport:
    async def test_a_report_is_recorded_and_counted(self, seams: Seams) -> None:
        await abuse.report(_link(), ReportReason.PHISHING, "reporter-1", signed_in=False)

        (stored,) = seams.reports.add.await_args.args
        assert (stored.slug, stored.reason, stored.reporter_key, stored.signed_in) == (
            SLUG,
            ReportReason.PHISHING,
            "reporter-1",
            False,
        )
        assert seams.capture.call_args_list == [_reported(signed_in=False)]
        seams.reports.signed_in_reporters.assert_awaited_once_with(SLUG)
        seams.links.update.assert_not_awaited()

    async def test_a_repeat_report_from_the_same_reporter_changes_nothing(
        self, seams: Seams
    ) -> None:
        seams.reports.add.return_value = False

        await abuse.report(_link(), ReportReason.PHISHING, "reporter-1", signed_in=True)

        seams.capture.assert_not_called()
        seams.reports.signed_in_reporters.assert_not_awaited()
        seams.links.update.assert_not_awaited()

    @pytest.mark.parametrize(
        ("snapshot", "access", "threshold"),
        [
            (_snapshot(RenderMode.FRAME_ACTIVE), LinkAccess.PUBLIC, 3),
            (_snapshot(RenderMode.DOWNLOAD), LinkAccess.UNLISTED, 3),
            (_snapshot(RenderMode.FRAME_ACTIVE), LinkAccess.PEOPLE, 5),
            (_snapshot(RenderMode.IMAGE), LinkAccess.PUBLIC, 5),
            (None, LinkAccess.PUBLIC, 5),
        ],
    )
    async def test_the_threshold_th_signed_in_reporter_suspends_the_link(
        self,
        seams: Seams,
        snapshot: LinkSnapshot | None,
        access: LinkAccess,
        threshold: int,
    ) -> None:
        link = _link(snapshot=snapshot, access=access)
        seams.reports.signed_in_reporters.return_value = threshold - 1
        await abuse.report(link, ReportReason.PHISHING, "reporter-1", signed_in=True)
        seams.links.update.assert_not_awaited()

        seams.reports.signed_in_reporters.return_value = threshold
        await abuse.report(link, ReportReason.PHISHING, "reporter-2", signed_in=True)

        seams.links.update.assert_awaited_once_with(
            SLUG, user_id=OWNER, update=ShortLinkUpdate(suspended=True)
        )
        assert seams.capture.call_args_list == [_reported(), _reported(), _suspended()]

    async def test_a_suspended_link_is_not_suspended_again(self, seams: Seams) -> None:
        seams.reports.signed_in_reporters.return_value = 10

        await abuse.report(_link(suspended=True), ReportReason.PHISHING, "r", signed_in=True)

        seams.links.update.assert_not_awaited()
        seams.send_email.assert_not_awaited()

    async def test_a_suspension_emails_every_support_inbox(self, seams: Seams) -> None:
        seams.reports.signed_in_reporters.return_value = 5

        async with captured_wide_event() as event:
            await abuse.report(_link(), ReportReason.PHISHING, "r", signed_in=True)

        assert event["errors"] == [
            {
                "msg": "short_link.suspended",
                "user_id": OWNER,
                "target_type": "session_artifact",
                "slug_hash": hash_short_link_slug(SLUG),
                "reporters": 5,
            }
        ]
        html = (
            f"<p>{settings.SHORTLINK_BASE_URL}/{SLUG} was suspended after 5 reports.</p>"
            f"<p>Owner: {OWNER}. Type: session_artifact.</p>"
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
        seams.reports.signed_in_reporters.return_value = 5

        await abuse.report(_link(), ReportReason.PHISHING, "r", signed_in=True)

        seams.links.update.assert_awaited_once()
        seams.send_email.assert_not_awaited()


class TestTakedown:
    async def test_a_takedown_revokes_deletes_the_file_and_is_counted(self, seams: Seams) -> None:
        snapshot = _snapshot(RenderMode.FRAME_ACTIVE)

        await abuse.take_down(_link(snapshot=snapshot))

        seams.links.revoke.assert_awaited_once_with(OWNER, SLUG, RevokeReason.TAKEDOWN)
        seams.delete_snapshot.assert_awaited_once_with(OWNER, snapshot)
        assert seams.capture.call_args_list == [
            call(UserId(OWNER), ShortLinkTakenDown(target_type="session_artifact", reason="admin"))
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
