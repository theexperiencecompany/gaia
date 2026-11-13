"""System notices: what makes two filings the same fact, and what a notice must carry."""

import pytest

from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    ProducerKind,
    SubjectKind,
)
from app.services.outbox.system_notices import system_notice, system_report_id

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
