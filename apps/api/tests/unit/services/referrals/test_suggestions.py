"""Suggestions rank real people from recent meetings and sent mail, skipping robots, lists and existing users."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest
import time_machine

from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.constants.referrals import SEND_AS_READ_FAILED_MESSAGE, SEND_AS_READ_FAILED_WHY
from app.models.calendar_models import GoogleCalendarEventResource
from app.models.integration_models import IntegrationAccount, UserIntegrationDocument
from app.models.mail_models import GmailMessagesResponse, GmailMessageSummary, GmailToolResult
from app.models.referral_models import ReferralSuggestionReason
from app.models.user_models import UserDocument
from app.services.mail.mail_service import MessageFetchOptions
from app.services.referrals.suggestions import is_automated, suggest_invitees
from app.utils.errors import AppError

MODULE = "app.services.referrals.suggestions"
ME = UserDocument(id="64abc123def4567890abcdef", email="me@example.com", first_name="Me")
NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
METADATA_ONLY = MessageFetchOptions(output_format="metadata", include_payload=False, verbose=False)


def _meeting(*emails: str) -> GoogleCalendarEventResource:
    return GoogleCalendarEventResource.model_validate(
        {
            "id": "e",
            "attendees": [{"email": e, "displayName": e.split("@")[0].title()} for e in emails],
        }
    )


def _sent(to: str, cc: str = "") -> GmailMessageSummary:
    return GmailMessageSummary.model_validate({"id": "m", "to": to, "cc": cc})


def _ranked(response) -> list[tuple[str, ReferralSuggestionReason, int]]:
    return [(s.email, s.reason, s.count) for s in response.suggestions]


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
        patch(f"{MODULE}.load_user", AsyncMock(return_value=ME)) as load_user,
        patch(
            f"{MODULE}.check_multiple_integrations_status",
            AsyncMock(return_value={"gmail": True, "googlecalendar": True}),
        ) as connected,
        patch(
            f"{MODULE}.get_calendar_events",
            AsyncMock(return_value=SimpleNamespace(events=meetings)),
        ) as calendar,
        patch(
            f"{MODULE}.search_messages",
            AsyncMock(return_value=GmailMessagesResponse(messages=sent)),
        ) as mail,
        patch(
            f"{MODULE}.referral_invite_repository.invited_by",
            AsyncMock(return_value={"invited@example.com"}),
        ) as invited,
        patch(
            f"{MODULE}.email_suppression_repository.suppressed_among", AsyncMock(return_value=set())
        ) as suppressed,
        patch(
            f"{MODULE}.user_repository.registered_emails",
            AsyncMock(return_value={"existing@example.com"}),
        ) as registered,
        patch(f"{MODULE}.get_account_record", AsyncMock(return_value=None)) as accounts,
        patch(
            f"{MODULE}.invoke_gmail_tool",
            AsyncMock(return_value=GmailToolResult(successful=True, data={"sendAs": []})),
        ) as gmail_tool,
    ):
        yield SimpleNamespace(
            load_user=load_user,
            connected=connected,
            calendar=calendar,
            mail=mail,
            invited=invited,
            suppressed=suppressed,
            registered=registered,
            accounts=accounts,
            gmail_tool=gmail_tool,
        )


async def test_people_are_ranked_by_how_often_with_the_stronger_reason(sources) -> None:
    response = await suggest_invitees(ME.id)

    assert _ranked(response) == [
        ("sam@example.com", ReferralSuggestionReason.EMAILED, 3),
        ("priya@example.com", ReferralSuggestionReason.MET, 3),
        ("lee@example.com", ReferralSuggestionReason.EMAILED, 1),
    ]
    assert [s.name for s in response.suggestions] == ["Sam", "Priya", "Lee"]


@time_machine.travel(NOW, tick=False)
async def test_the_last_90_days_of_the_users_own_calendar_and_sent_mail_are_read(
    sources,
) -> None:
    await suggest_invitees(ME.id)

    sources.load_user.assert_awaited_once_with(ME.id)
    sources.connected.assert_awaited_once_with(
        [GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID], ME.id
    )
    sources.calendar.assert_awaited_once_with(
        ME.id,
        time_min=(NOW - timedelta(days=90)).isoformat(),
        time_max=NOW.isoformat(),
        fetch_all=True,
    )
    sources.mail.assert_awaited_once_with(
        ME.id,
        query="in:sent newer_than:90d",
        max_results=100,
        page_token=None,
        options=METADATA_ONLY,
    )


async def test_sent_mail_is_read_page_after_page_until_none_is_left(sources) -> None:
    sources.connected.return_value = {"gmail": True}
    sources.mail.side_effect = [
        GmailMessagesResponse(messages=[_sent("lee@example.com")], next_page_token="p2"),
        GmailMessagesResponse(messages=[_sent("kim@example.com")]),
    ]

    response = await suggest_invitees(ME.id)

    assert [c.kwargs["page_token"] for c in sources.mail.await_args_list] == [None, "p2"]
    assert {s.email for s in response.suggestions} == {"lee@example.com", "kim@example.com"}


async def test_sent_mail_stops_after_five_pages(sources) -> None:
    sources.connected.return_value = {"gmail": True}
    sources.mail.return_value = GmailMessagesResponse(
        messages=[_sent("lee@example.com")], next_page_token="more"
    )

    await suggest_invitees(ME.id)

    assert sources.mail.await_count == 5


async def test_the_exclusion_lookups_cover_every_candidate(sources) -> None:
    sources.connected.return_value = {"gmail": True}
    sources.mail.return_value = GmailMessagesResponse(
        messages=[_sent("Lee <Lee@Example.com>, a.ryan+x@gmail.com")]
    )

    await suggest_invitees(ME.id)

    sources.invited.assert_awaited_once_with(ME.id)
    sources.suppressed.assert_awaited_once_with(["lee@example.com", "aryan@gmail.com"])
    sources.registered.assert_awaited_once_with(["lee@example.com", "a.ryan+x@gmail.com"])


async def test_an_opted_out_address_is_never_suggested(sources) -> None:
    sources.connected.return_value = {"gmail": True}
    sources.mail.return_value = GmailMessagesResponse(
        messages=[_sent("lee@example.com, kim@example.com")]
    )
    sources.suppressed.return_value = {"kim@example.com"}

    assert _ranked(await suggest_invitees(ME.id)) == [
        ("lee@example.com", ReferralSuggestionReason.EMAILED, 1)
    ]


async def test_meetings_up_to_ten_people_count_and_bigger_ones_are_skipped(sources) -> None:
    sources.connected.return_value = {"googlecalendar": True}
    sources.calendar.return_value = SimpleNamespace(
        events=[
            _meeting(*[f"big{i}@example.com" for i in range(11)]),
            _meeting(*[f"ten{i}@example.com" for i in range(10)]),
            _meeting("after@example.com"),
        ]
    )

    emails = {s.email for s in (await suggest_invitees(ME.id)).suggestions}

    assert "ten0@example.com" in emails and "after@example.com" in emails
    assert not any(email.startswith("big") for email in emails)


async def test_someone_met_as_often_as_emailed_is_suggested_as_met(sources) -> None:
    sources.calendar.return_value = SimpleNamespace(events=[_meeting("lee@example.com")])
    sources.mail.return_value = GmailMessagesResponse(messages=[_sent("lee@example.com")])

    assert _ranked(await suggest_invitees(ME.id)) == [
        ("lee@example.com", ReferralSuggestionReason.MET, 1)
    ]


async def test_the_wide_event_records_sources_candidates_and_suggestions(sources) -> None:
    sources.connected.return_value = {"gmail": True, "googlecalendar": False}
    sources.mail.return_value = GmailMessagesResponse(
        messages=[_sent("lee@example.com, existing@example.com")]
    )

    with patch(f"{MODULE}.log") as log:
        await suggest_invitees(ME.id)

    assert log.set_ns.call_args_list == [
        call(
            "referral",
            suggestion_sources=["gmail"],
            suggestion_candidates=2,
            suggestions=1,
        )
    ]


async def test_nothing_connected_suggests_nobody(sources) -> None:
    sources.connected.return_value = {"gmail": False, "googlecalendar": False}

    assert (await suggest_invitees(ME.id)).suggestions == []
    sources.mail.assert_not_called()
    sources.calendar.assert_not_called()


@pytest.mark.parametrize(
    ("address", "automated"),
    [
        ("no-reply@shop.com", True),
        ("Notifications@github.com", True),
        ("team@googlegroups.com", True),
        ("priya@example.com", False),
        ("ann.support.lead@corp.com", True),
        ("startups@openrouter.ai", True),
        ("deals@hustlefund.vc", True),
        ("compliance-team@openphone.co", True),
        ("aws-activate@amazon.com", True),
        ("hello+eu@brand.io", True),
        ("will@m3ga.life", False),
        ("teamlead.ana@corp.com", False),
        # The domain is what follows the last @; a quoted local part may hold one.
        ('"team@no-reply"@example.com', True),
        ('"x@lists.y"@person.com', False),
        ("32.mrtvgqtl@unsubscribe2.customer.io", True),
        ("bounces+123@em.mailer.com", True),
    ],
)
def test_robots_and_lists_are_recognised(address: str, automated: bool) -> None:
    assert is_automated(address) is automated


async def test_the_users_other_mailboxes_and_send_as_aliases_are_never_suggested(
    sources,
) -> None:
    sources.connected.return_value = {"gmail": True}
    sources.mail.return_value = GmailMessagesResponse(
        messages=[
            _sent("me@work.example, Me <me.personal@gmail.com>, alias@me.example, me@example.com"),
            _sent("lee@example.com"),
        ]
    )
    sources.accounts.return_value = UserIntegrationDocument(
        user_id=ME.id,
        integration_id="gmail",
        accounts=[
            IntegrationAccount(
                id="a1",
                connected_account_id="ca_1",
                identity={"email": "Me.Personal@gmail.com"},
                label="Me.Personal@gmail.com",
            ),
            IntegrationAccount(id="a2", connected_account_id="ca_2", identity={}, label="unnamed"),
        ],
    )
    sources.gmail_tool.return_value = GmailToolResult(
        successful=True,
        data={"sendAs": [{"sendAsEmail": "me@work.example"}, {"sendAsEmail": "Alias@me.example"}]},
    )

    response = await suggest_invitees(ME.id)

    assert [s.email for s in response.suggestions] == ["lee@example.com"]
    sources.accounts.assert_awaited_once_with(ME.id, "gmail")
    sources.gmail_tool.assert_awaited_once_with(ME.id, "GMAIL_LIST_SEND_AS", {"user_id": "me"})


async def test_a_refused_send_as_read_fails_loudly(sources) -> None:
    sources.connected.return_value = {"gmail": True}
    sources.gmail_tool.return_value = GmailToolResult(successful=False, error="scope missing")

    with pytest.raises(AppError) as refused:
        await suggest_invitees(ME.id)

    assert refused.value.status_code == 502
    assert refused.value.to_dict() == {
        "message": SEND_AS_READ_FAILED_MESSAGE,
        "why": SEND_AS_READ_FAILED_WHY,
        "provider_error": "scope missing",
    }


async def test_without_gmail_no_send_as_aliases_are_read(sources) -> None:
    sources.connected.return_value = {"googlecalendar": True}

    await suggest_invitees(ME.id)

    sources.gmail_tool.assert_not_awaited()


async def test_a_mailbox_named_after_the_user_is_their_own(sources) -> None:
    named = ME.model_copy(update={"name": "Aryan Randeriya"})
    sources.load_user.return_value = named
    sources.connected.return_value = {"gmail": True}
    sources.mail.return_value = GmailMessagesResponse(
        messages=[
            _sent("aryan.k.randeriya@gmail.com, randeriya.family@gmail.com"),
            _sent("Aryan Shah <aryan@corp.com>"),
        ]
    )

    response = await suggest_invitees(named.id)

    assert [s.email for s in response.suggestions] == [
        "randeriya.family@gmail.com",
        "aryan@corp.com",
    ]


@pytest.mark.parametrize(
    ("name", "address", "own"),
    [
        ("Ana Lee", "ana.lee.home@gmail.com", True),
        ("Ana Lee", "ana@corp.com", False),
        ("Aryan", "aryan@corp.com", False),
        ("Al Bo", "al.bo@corp.com", False),
        (None, "me.too@corp.com", False),
    ],
)
async def test_only_a_full_name_match_marks_a_mailbox_as_the_users(
    sources, name: str | None, address: str, own: bool
) -> None:
    named = ME.model_copy(update={"name": name})
    sources.load_user.return_value = named
    sources.connected.return_value = {"gmail": True}
    sources.mail.return_value = GmailMessagesResponse(messages=[_sent(address)])

    response = await suggest_invitees(named.id)

    assert [s.email for s in response.suggestions] == ([] if own else [address])
