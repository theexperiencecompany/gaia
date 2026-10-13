"""Suggestions rank real people from recent meetings and sent mail, skipping robots, lists and existing users."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.calendar_models import GoogleCalendarEventResource
from app.models.mail_models import GmailMessagesResponse, GmailMessageSummary
from app.models.referral_models import ReferralSuggestionReason
from app.models.user_models import UserDocument
from app.services.referrals.suggestions import is_automated, suggest_invitees

MODULE = "app.services.referrals.suggestions"
ME = UserDocument(id="64abc123def4567890abcdef", email="me@example.com", first_name="Me")


def _meeting(*emails: str) -> GoogleCalendarEventResource:
    return GoogleCalendarEventResource.model_validate(
        {
            "id": "e",
            "attendees": [{"email": e, "displayName": e.split("@")[0].title()} for e in emails],
        }
    )


def _sent(to: str, cc: str = "") -> GmailMessageSummary:
    return GmailMessageSummary.model_validate({"id": "m", "to": to, "cc": cc})


@pytest.fixture
def sources() -> Iterator[SimpleNamespace]:
    meetings = [
        _meeting("me@example.com", "priya@example.com"),
        _meeting("priya@example.com", "sam@example.com"),
        _meeting("priya@example.com"),
        _meeting(*[f"p{i}@example.com" for i in range(11)]),
        _meeting("room@resource.calendar.google.com", "sam@example.com"),
    ]
    sent = [
        _sent("Sam <sam@example.com>", "no-reply@shop.com"),
        _sent("sam@example.com, Lee <lee@example.com>"),
        _sent("team@googlegroups.com, Sam <SAM@Example.com>"),
        _sent("existing@example.com"),
        _sent("invited@example.com"),
    ]
    with (
        patch(f"{MODULE}.load_user", AsyncMock(return_value=ME)),
        patch(
            f"{MODULE}.check_multiple_integrations_status",
            AsyncMock(return_value={"gmail": True, "googlecalendar": True}),
        ) as connected,
        patch(
            f"{MODULE}.get_calendar_events",
            AsyncMock(return_value=SimpleNamespace(events=meetings)),
        ),
        patch(
            f"{MODULE}.search_messages",
            AsyncMock(return_value=GmailMessagesResponse(messages=sent)),
        ) as mail,
        patch(
            f"{MODULE}.referral_invite_repository.invited_by",
            AsyncMock(return_value={"invited@example.com"}),
        ),
        patch(
            f"{MODULE}.email_suppression_repository.suppressed_among", AsyncMock(return_value=set())
        ),
        patch(
            f"{MODULE}.user_repository.registered_emails",
            AsyncMock(return_value={"existing@example.com"}),
        ),
    ):
        yield SimpleNamespace(connected=connected, mail=mail)


async def test_people_are_ranked_by_how_often_with_the_stronger_reason(sources) -> None:
    response = await suggest_invitees(ME.id)

    ranked = [(s.email, s.reason, s.count) for s in response.suggestions]
    assert ranked == [
        ("sam@example.com", ReferralSuggestionReason.EMAILED, 3),
        ("priya@example.com", ReferralSuggestionReason.MET, 3),
        ("lee@example.com", ReferralSuggestionReason.EMAILED, 1),
    ]
    assert response.suggestions[1].name == "Priya"


async def test_nothing_connected_suggests_nobody(sources) -> None:
    sources.connected.return_value = {"gmail": False, "googlecalendar": False}

    assert (await suggest_invitees(ME.id)).suggestions == []
    sources.mail.assert_not_called()


@pytest.mark.parametrize(
    ("address", "automated"),
    [
        ("no-reply@shop.com", True),
        ("Notifications@github.com", True),
        ("team@googlegroups.com", True),
        ("priya@example.com", False),
        ("ann.support.lead@corp.com", True),
    ],
)
def test_robots_and_lists_are_recognised(address: str, automated: bool) -> None:
    assert is_automated(address) is automated
