"""The access matrix: every level, viewer and state decides exactly one way."""

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
import pytest

from app.models.short_link_models import (
    LinkAccess,
    LinkDenial,
    LinkSnapshot,
    LinkViewer,
    LinkViewerKind,
    RecordTarget,
    RenderMode,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.links.access import (
    Denied,
    Granted,
    at_most,
    evaluate,
    is_open,
    servable_content,
)

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
        "target": RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id="t1"),
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


# Dead states: everyone but the owner sees the denial. The owner still opens a link they
# turned off, rotated or let expire (their own emails and QR codes carry it); a takedown
# or a deleted target closes it for them too.
DEAD_STATES = [
    ({"expires_at": NOW}, LinkDenial.EXPIRED, _OWNER),
    ({"expires_at": NOW - timedelta(seconds=1)}, LinkDenial.EXPIRED, _OWNER),
    ({"revoked": True, "revoked_reason": RevokeReason.OWNER}, LinkDenial.REVOKED, _OWNER),
    ({"revoked": True, "revoked_reason": RevokeReason.ROTATED}, LinkDenial.REVOKED, _OWNER),
    ({"revoked": True, "revoked_reason": RevokeReason.EXPIRED}, LinkDenial.EXPIRED, _OWNER),
    (
        {"revoked": True, "revoked_reason": RevokeReason.TAKEDOWN},
        LinkDenial.REMOVED,
        Denied(LinkDenial.REMOVED),
    ),
    (
        {"revoked": True, "revoked_reason": RevokeReason.TARGET_DELETED},
        LinkDenial.TARGET_DELETED,
        Denied(LinkDenial.TARGET_DELETED),
    ),
    ({"suspended": True}, LinkDenial.REMOVED, Denied(LinkDenial.REMOVED)),
    # Suspension wins over a later expiry: the link was removed first.
    (
        {"suspended": True, "expires_at": NOW - timedelta(days=1)},
        LinkDenial.REMOVED,
        Denied(LinkDenial.REMOVED),
    ),
]


@pytest.mark.parametrize("access", list(LinkAccess))
@pytest.mark.parametrize("viewer", [ANON, GRANTEE, STRANGER, SLACKBOT])
@pytest.mark.parametrize(("state", "denial", "_owner_sees"), DEAD_STATES)
def test_a_dead_link_opens_for_no_one_but_maybe_its_owner(
    access: LinkAccess,
    viewer: LinkViewer,
    state: dict[str, object],
    denial: LinkDenial,
    _owner_sees: Granted | Denied,
) -> None:
    assert evaluate(_link(access, **state), viewer, NOW) == Denied(denial)


@pytest.mark.parametrize("access", list(LinkAccess))
@pytest.mark.parametrize(("state", "_denial", "owner_sees"), DEAD_STATES)
def test_the_owner_opens_what_they_turned_off_but_not_what_was_removed_or_deleted(
    access: LinkAccess,
    state: dict[str, object],
    _denial: LinkDenial,
    owner_sees: Granted | Denied,
) -> None:
    assert evaluate(_link(access, **state), OWNER, NOW) == owner_sees


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


@pytest.mark.parametrize(
    ("access", "opens"),
    [
        (LinkAccess.PUBLIC, True),
        (LinkAccess.UNLISTED, True),
        (LinkAccess.PEOPLE, False),
        (LinkAccess.OWNER, False),
    ],
)
def test_only_public_and_unlisted_links_are_open(access: LinkAccess, opens: bool) -> None:
    assert is_open(access) is opens


def _file(**overrides: object) -> LinkSnapshot:
    data: dict[str, object] = {
        "filename": "r.html",
        "mime": "text/html",
        "size_bytes": 4,
        "render": RenderMode.FRAME_ACTIVE,
        "content_id": "c" * 26,
        "max_access": LinkAccess.PEOPLE,
    }
    data.update(overrides)
    return LinkSnapshot.model_validate(data)


@pytest.mark.parametrize(
    ("link", "serves"),
    [
        (_link(LinkAccess.PEOPLE, snapshot=_file()), True),
        (_link(LinkAccess.UNLISTED, snapshot=_file()), False),
        (_link(LinkAccess.PEOPLE, snapshot=_file(content_id=None)), False),
        (_link(LinkAccess.PEOPLE), False),
        (_link(LinkAccess.PEOPLE, snapshot=_file(), suspended=True), False),
        (_link(LinkAccess.PEOPLE, snapshot=_file(), expires_at=NOW), False),
    ],
)
def test_a_link_serves_its_bytes_only_live_published_and_within_their_cap(
    link: ShortLink, serves: bool
) -> None:
    assert (servable_content(link, NOW) is not None) is serves


@pytest.mark.parametrize(
    "fields", [{"revoked": True}, {"revoked": False, "revoked_reason": RevokeReason.OWNER}]
)
def test_a_link_is_revoked_exactly_when_it_says_why(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="revoked exactly when"):
        _link(LinkAccess.UNLISTED, **fields)
