"""The closed set of fixed copy: keyed by locale, filled from what the producer names, refusing what it does not need."""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
)
from app.services.outbox.prerendered import (
    PrerenderedKind,
    PrerenderedMessage,
    prerendered_parts,
    prerendered_text,
)


def test_the_connected_confirmation_names_the_platform_and_points_at_help() -> None:
    message = PrerenderedMessage(kind=PrerenderedKind.ACCOUNT_LINKED, platform="Telegram")

    assert prerendered_parts(message, "en") == [
        "✅ **You're connected**\n\n"
        "Your Telegram account is linked. "
        "Message me anytime, or send `/help` to see what I can do."
    ]


def test_a_locale_with_no_copy_is_said_in_the_default_locale() -> None:
    assert prerendered_text(PrerenderedKind.COMPOSE_DEGRADED, "hi") == prerendered_text(
        PrerenderedKind.COMPOSE_DEGRADED, "en"
    )


def test_a_first_contact_says_the_bubbles_its_producer_built() -> None:
    message = PrerenderedMessage(
        kind=PrerenderedKind.FIRST_CONTACT, bubbles=["Hey, I'm with you on Telegram now.", "Go."]
    )

    assert prerendered_parts(message, "en") == ["Hey, I'm with you on Telegram now.", "Go."]


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": PrerenderedKind.ACCOUNT_LINKED},
        {"kind": PrerenderedKind.ACCOUNT_LINKED, "platform": "Telegram", "bubbles": ["x"]},
        {"kind": PrerenderedKind.FIRST_CONTACT},
        {"kind": PrerenderedKind.FIRST_CONTACT, "bubbles": ["x"], "platform": "Telegram"},
        {"kind": PrerenderedKind.COMPOSE_DEGRADED, "platform": "Telegram"},
    ],
)
def test_a_message_must_carry_exactly_what_its_kind_needs(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PrerenderedMessage.model_validate(fields)


def _notice(**overrides: object) -> NoticeReport:
    fields: dict[str, object] = {
        "report_id": "n",
        "recipient": "u",
        "producer": ProducerKind.ACCOUNT,
        "subject": Subject(kind=SubjectKind.ACCOUNT, id="a", label="A"),
        "occurred_at": datetime(2026, 11, 10, tzinfo=UTC),
        "initiative": Initiative.ASKED,
        "outcome": NoticeOutcome.INFO,
    }
    return NoticeReport.model_validate({**fields, **overrides})


def test_a_notice_that_says_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="facts, artifacts or a prerendered"):
        _notice()


def test_a_prerendered_notice_needs_no_facts() -> None:
    notice = _notice(prerendered={"kind": "account_linked", "platform": "Telegram"})

    assert notice.facts == []
