"""The access matrix: every level, viewer and state decides exactly one way."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.short_link_models import (
    LinkAccess,
    LinkDenial,
    LinkViewer,
    LinkViewerKind,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.links.access import Denied, Granted, at_most, evaluate

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
OWNER_ID = "507f1f77bcf86cd799439011"
GRANTEE_EMAIL = "Friend@Example.com"
BROWSER = "Mozilla/5.0 (Macintosh) Safari/605.1.15"

ANON = LinkViewer(user_id=None, email=None, ip="1.2.3.4", user_agent=BROWSER)
OWNER = LinkViewer(user_id=OWNER_ID, email="owner@example.com", ip="1.2.3.4", user_agent=BROWSER)
# The grant matches the account email case-insensitively.
GRANTEE = LinkViewer(user_id="g", email="friend@example.com", ip="1.2.3.4", user_agent=BROWSER)
STRANGER = LinkViewer(user_id="s", email="someone@example.com", ip="1.2.3.4", user_agent=BROWSER)
NO_EMAIL = LinkViewer(user_id="n", email=None, ip="1.2.3.4", user_agent=BROWSER)
SLACKBOT = LinkViewer(
    user_id=None, email=None, ip="1.2.3.4", user_agent="Slackbot-LinkExpanding 1.0"
)


def _link(access: LinkAccess, **overrides: object) -> ShortLink:
    data: dict[str, object] = {
        "slug": "abcdefghijk",
        "user_id": OWNER_ID,
        "target_type": ShortLinkTargetType.TODO_DELIVERABLE,
        "target_id": "t1",
        "access": access,
        "grantees": [GRANTEE_EMAIL],
    }
    data.update(overrides)
    return ShortLink.model_validate(data)


_RECIPIENT = Granted(LinkViewerKind.RECIPIENT)
_OWNER = Granted(LinkViewerKind.OWNER)
_SIGN_IN = Denied(LinkDenial.SIGN_IN_REQUIRED)
_FORBIDDEN = Denied(LinkDenial.FORBIDDEN)

# Live links: level x viewer.
LIVE_MATRIX = [
    (LinkAccess.PUBLIC, ANON, _RECIPIENT),
    (LinkAccess.PUBLIC, OWNER, _OWNER),
    (LinkAccess.PUBLIC, GRANTEE, _RECIPIENT),
    (LinkAccess.PUBLIC, STRANGER, _RECIPIENT),
    (LinkAccess.UNLISTED, ANON, _RECIPIENT),
    (LinkAccess.UNLISTED, OWNER, _OWNER),
    (LinkAccess.UNLISTED, GRANTEE, _RECIPIENT),
    (LinkAccess.UNLISTED, STRANGER, _RECIPIENT),
    (LinkAccess.PEOPLE, ANON, _SIGN_IN),
    (LinkAccess.PEOPLE, OWNER, _OWNER),
    (LinkAccess.PEOPLE, GRANTEE, _RECIPIENT),
    (LinkAccess.PEOPLE, STRANGER, _FORBIDDEN),
    (LinkAccess.PEOPLE, NO_EMAIL, _FORBIDDEN),
    (LinkAccess.OWNER, ANON, _SIGN_IN),
    (LinkAccess.OWNER, OWNER, _OWNER),
    (LinkAccess.OWNER, GRANTEE, _FORBIDDEN),
    (LinkAccess.OWNER, STRANGER, _FORBIDDEN),
]


@pytest.mark.parametrize(("access", "viewer", "expected"), LIVE_MATRIX)
def test_a_live_link_opens_for_exactly_its_level(
    access: LinkAccess, viewer: LinkViewer, expected: Granted | Denied
) -> None:
    assert evaluate(_link(access), viewer, NOW) == expected


# Dead states: every viewer, the owner included, sees the same denial.
DEAD_STATES = [
    ({"expires_at": NOW}, LinkDenial.EXPIRED),
    ({"expires_at": NOW - timedelta(seconds=1)}, LinkDenial.EXPIRED),
    ({"revoked": True, "revoked_reason": RevokeReason.OWNER}, LinkDenial.REVOKED),
    ({"revoked": True, "revoked_reason": RevokeReason.ROTATED}, LinkDenial.REVOKED),
    ({"revoked": True, "revoked_reason": RevokeReason.EXPIRED}, LinkDenial.EXPIRED),
    ({"revoked": True, "revoked_reason": RevokeReason.TAKEDOWN}, LinkDenial.REMOVED),
    (
        {"revoked": True, "revoked_reason": RevokeReason.TARGET_DELETED},
        LinkDenial.TARGET_DELETED,
    ),
    # A link revoked before reasons existed reads as the owner's revoke.
    ({"revoked": True}, LinkDenial.REVOKED),
    ({"suspended": True}, LinkDenial.REMOVED),
    # Suspension wins over a later expiry: the link was removed first.
    ({"suspended": True, "expires_at": NOW - timedelta(days=1)}, LinkDenial.REMOVED),
]


@pytest.mark.parametrize("access", list(LinkAccess))
@pytest.mark.parametrize("viewer", [ANON, OWNER, GRANTEE, STRANGER])
@pytest.mark.parametrize(("state", "denial"), DEAD_STATES)
def test_a_dead_link_opens_for_no_one(
    access: LinkAccess, viewer: LinkViewer, state: dict[str, object], denial: LinkDenial
) -> None:
    assert evaluate(_link(access, **state), viewer, NOW) == Denied(denial)


def test_a_future_expiry_is_still_live() -> None:
    link = _link(LinkAccess.UNLISTED, expires_at=NOW + timedelta(seconds=1))
    assert evaluate(link, ANON, NOW) == _RECIPIENT


def test_an_unknown_slug_is_not_found() -> None:
    assert evaluate(None, OWNER, NOW) == Denied(LinkDenial.NOT_FOUND)


@pytest.mark.parametrize("access", [LinkAccess.PUBLIC, LinkAccess.UNLISTED])
def test_an_unfurl_bot_opens_an_open_link_as_a_bot(access: LinkAccess) -> None:
    assert evaluate(_link(access), SLACKBOT, NOW) == Granted(LinkViewerKind.UNFURL_BOT)


@pytest.mark.parametrize("access", [LinkAccess.PEOPLE, LinkAccess.OWNER])
def test_an_unfurl_bot_never_opens_a_gated_link(access: LinkAccess) -> None:
    assert evaluate(_link(access), SLACKBOT, NOW) == _SIGN_IN


@pytest.mark.parametrize(
    ("access", "cap", "fits"),
    [
        (LinkAccess.OWNER, LinkAccess.OWNER, True),
        (LinkAccess.PEOPLE, LinkAccess.OWNER, False),
        (LinkAccess.PEOPLE, LinkAccess.PEOPLE, True),
        (LinkAccess.UNLISTED, LinkAccess.PEOPLE, False),
        (LinkAccess.UNLISTED, LinkAccess.PUBLIC, True),
        (LinkAccess.PUBLIC, LinkAccess.UNLISTED, False),
        (LinkAccess.PUBLIC, LinkAccess.PUBLIC, True),
    ],
)
def test_at_most_orders_levels_by_who_they_open_for(
    access: LinkAccess, cap: LinkAccess, fits: bool
) -> None:
    assert at_most(access, cap) is fits
