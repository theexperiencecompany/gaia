"""Guessing lockout, reports, automatic suspension and admin takedown of heygaia.link links."""

from app.config.settings import settings
from app.constants.email import SUPPORT_SENDER
from app.constants.short_links import (
    ACTIVE_CONTENT_REPORT_THRESHOLD,
    MAX_RESOLVE_MISSES,
    REPORT_THRESHOLD,
    RESOLVE_LOCKOUT_KEY,
    RESOLVE_MISS_KEY,
    RESOLVE_MISS_LOCKOUT_SECONDS,
    RESOLVE_MISS_WINDOW_SECONDS,
)
from app.db.redis import redis_cache
from app.db.repositories.link_reports import link_report_repository
from app.db.repositories.short_links import short_link_repository
from app.models.short_link_models import (
    LinkAccess,
    LinkReport,
    RenderMode,
    ReportReason,
    RevokeReason,
    ShortLink,
    ShortLinkUpdate,
)
from app.services.analytics_service import capture
from app.services.email.models import EmailMessage
from app.services.email.service import send_email
from app.services.links.content import delete_snapshot
from app.services.links.service import build_url
from app.services.support_service import SUPPORT_EMAILS
from app.utils.errors import AppError
from app.utils.log_identifiers import hash_short_link_slug
from shared.py.analytics import UserId
from shared.py.analytics.catalog.short_links import ShortLinkReported, ShortLinkTakenDown
from shared.py.wide_events import log

# Content that can phish or carry malware is suspended on fewer reports.
_ACTIVE_RENDERS = frozenset({RenderMode.FRAME_ACTIVE, RenderMode.DOWNLOAD})
_OPEN_ACCESS = frozenset({LinkAccess.PUBLIC, LinkAccess.UNLISTED})


def _locked_out() -> AppError:
    return AppError(
        message="Too many links that don't exist were opened from here",
        fix="Try again in an hour",
        status_code=429,
        code="link_lookup_locked",
    )


async def refuse_when_locked_out(viewer: str) -> None:
    """Raise 429 while viewer is locked out for guessing slugs."""
    if await redis_cache.client.exists(RESOLVE_LOCKOUT_KEY.format(viewer=viewer)):
        raise _locked_out()


async def record_miss(viewer: str, slug: str) -> None:
    """Count one unknown slug for viewer; past MAX_RESOLVE_MISSES distinct ones, lock them out."""
    key = RESOLVE_MISS_KEY.format(viewer=viewer)
    await redis_cache.client.sadd(key, hash_short_link_slug(slug))
    await redis_cache.client.expire(key, RESOLVE_MISS_WINDOW_SECONDS)
    if len(await redis_cache.client.smembers(key)) > MAX_RESOLVE_MISSES:
        await redis_cache.client.setex(
            RESOLVE_LOCKOUT_KEY.format(viewer=viewer), RESOLVE_MISS_LOCKOUT_SECONDS, "1"
        )
        log.warning("short_link.lookup_locked_out")
        raise _locked_out()


def _threshold(link: ShortLink) -> int:
    active = link.snapshot is not None and link.snapshot.render in _ACTIVE_RENDERS
    if active and link.access in _OPEN_ACCESS:
        return ACTIVE_CONTENT_REPORT_THRESHOLD
    return REPORT_THRESHOLD


async def _notify_support(link: ShortLink, reporters: int) -> None:
    """Tell GAIA's support inbox a link was suspended; self-host has no inbox, so it only logs."""
    log.error(
        "short_link.suspended",
        user_id=link.user_id,
        target_type=link.target_type.value,
        slug_hash=hash_short_link_slug(link.slug),
        reporters=reporters,
    )
    if not settings.deployment.gaia_support:
        return
    html = (
        f"<p>{build_url(link.slug)} was suspended after {reporters} reports.</p>"
        f"<p>Owner: {link.user_id}. Type: {link.target_type.value}.</p>"
        "<p>Restore it with <code>apps/api/scripts/link_takedown.py --slug SLUG --restore</code>, "
        "or take it down with <code>--reason admin</code>.</p>"
    )
    for address in SUPPORT_EMAILS:
        await send_email(
            EmailMessage(
                sender=SUPPORT_SENDER,
                to=[address],
                subject="A shared GAIA link was suspended",
                html=html,
            )
        )


async def report(
    link: ShortLink, reason: ReportReason, reporter_key: str, *, signed_in: bool
) -> None:
    """Record a report; the threshold-th distinct reporter suspends the link."""
    added = await link_report_repository.add(
        LinkReport(slug=link.slug, reason=reason, reporter_key=reporter_key)
    )
    if not added:
        return
    capture(
        UserId(link.user_id),
        ShortLinkReported(
            target_type=link.target_type.value, reason=reason.value, reporter_signed_in=signed_in
        ),
    )
    reporters = await link_report_repository.distinct_reporters(link.slug)
    if link.suspended or reporters < _threshold(link):
        return
    await short_link_repository.update(
        link.slug, user_id=link.user_id, update=ShortLinkUpdate(suspended=True)
    )
    capture(
        UserId(link.user_id),
        ShortLinkTakenDown(target_type=link.target_type.value, reason="reports_threshold"),
    )
    await _notify_support(link, reporters)


async def take_down(link: ShortLink) -> None:
    """Remove a link for breaking the terms: it dies for good and its file is deleted."""
    await short_link_repository.revoke(link.user_id, link.slug, RevokeReason.TAKEDOWN)
    if link.snapshot is not None:
        await delete_snapshot(link.user_id, link.snapshot)
    capture(
        UserId(link.user_id),
        ShortLinkTakenDown(target_type=link.target_type.value, reason="admin"),
    )


async def restore(link: ShortLink) -> None:
    """Lift a report suspension; a link already taken down stays dead with its file gone."""
    await short_link_repository.update(
        link.slug, user_id=link.user_id, update=ShortLinkUpdate(suspended=False)
    )
