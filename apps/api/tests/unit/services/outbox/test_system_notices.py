"""System notices: what makes two filings the same fact, and what a notice must carry."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.outbox import system_notices
from app.services.outbox.models import (
    NEEDS_YOU_OUTCOMES,
    Initiative,
    NoticeAction,
    NoticeActionKind,
    NoticeOutcome,
    ProducerKind,
    SubjectKind,
)
from app.services.outbox.system_notices import (
    settle_system_notices,
    system_notice,
    system_report_id,
)

USER = "6812f0b3c9a14e2b7d5a91cc"


def _notice(**fields: object):
    arguments: dict[str, object] = {
        "user_id": USER,
        "producer": ProducerKind.ACCOUNT,
        "subject_kind": SubjectKind.ACCOUNT,
        "kind": "memory_ready",
        "key": USER,
        "label": "Your memory",
        "outcome": NoticeOutcome.INFO,
        "facts": ["Memories were organized."],
        "display": "Your memories are ready.",
    }
    return system_notice(**{**arguments, **fields})  # type: ignore[arg-type]


def test_a_notice_is_named_by_its_kind_and_natural_key() -> None:
    notice = _notice(kind="integration_expired", key="notion:ca_1")

    assert notice.report_id == "sys:integration_expired:notion:ca_1"
    assert notice.report_id == system_report_id("integration_expired", "notion:ca_1")
    assert notice.subject.id == "integration_expired:notion:ca_1"


def test_the_same_occurrence_is_the_same_report_and_another_is_not() -> None:
    assert _notice().report_id == _notice().report_id
    assert _notice(key="other-user").report_id != _notice().report_id


def test_a_system_notice_is_self_initiated_unless_the_user_set_it_up() -> None:
    assert _notice().initiative is Initiative.SELF_INITIATED
    assert _notice(initiative=Initiative.USER_SCHEDULED).initiative is Initiative.USER_SCHEDULED


def test_a_notice_with_nothing_to_say_is_refused() -> None:
    with pytest.raises(ValueError, match="carries facts"):
        _notice(facts=[])


def test_a_notice_carries_the_line_the_feed_shows_beside_the_facts_the_composer_words() -> None:
    notice = _notice(display="Your memories are ready.")

    assert notice.display is not None
    assert (notice.display.line, notice.display.action) == ("Your memories are ready.", None)
    assert notice.facts == ["Memories were organized."]


def test_a_notice_names_the_one_thing_it_offers_the_user_to_do() -> None:
    action = NoticeAction(kind=NoticeActionKind.RECONNECT_INTEGRATION, integration_id="notion")

    notice = _notice(action=action)

    assert notice.display is not None
    assert notice.display.action == action


def test_reconnecting_an_integration_without_naming_it_is_refused() -> None:
    with pytest.raises(ValueError, match="names it"):
        NoticeAction(kind=NoticeActionKind.RECONNECT_INTEGRATION)


async def test_settling_resolves_the_needs_you_notices_of_one_kind_and_key_prefix() -> None:
    with patch.object(
        system_notices.outbox_items_repository, "settle_with_prefix", new_callable=AsyncMock
    ) as settle:
        settle.return_value = 1

        assert await settle_system_notices(USER, "integration_expired", "notion:ca_1:") == 1

    settle.assert_awaited_once_with(
        USER, "sys:integration_expired:notion:ca_1:", outcomes=NEEDS_YOU_OUTCOMES
    )
