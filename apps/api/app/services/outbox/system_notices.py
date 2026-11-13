"""System notices: what GAIA's own machinery tells the user, filed as notices with the facts and no words.

Every notice is named sys:{kind}:{key}, so a producer that fires twice for one occurrence files it
once. Whether, when and how the user is told is the outbox's to decide, as for any other report.
"""

from datetime import datetime

from app.constants.outbox import SYSTEM_REPORT_PREFIX
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
)
from app.utils import clock


def system_report_id(kind: str, key: str) -> str:
    """Return the report id of the notice of one kind and natural key."""
    return f"{SYSTEM_REPORT_PREFIX}{kind}:{key}"


def system_notice(
    *,
    user_id: str,
    producer: ProducerKind,
    subject_kind: SubjectKind,
    kind: str,
    key: str,
    label: str,
    outcome: NoticeOutcome,
    facts: list[str],
    initiative: Initiative = Initiative.SELF_INITIATED,
    owner_conversation_id: str | None = None,
    valid_until: datetime | None = None,
) -> NoticeReport:
    """Return the notice that tells user_id what happened, named by its kind and the occurrence's natural key."""
    occurrence = f"{kind}:{key}"
    return NoticeReport(
        report_id=system_report_id(kind, key),
        recipient=user_id,
        producer=producer,
        subject=Subject(
            kind=subject_kind,
            id=occurrence,
            owner_conversation_id=owner_conversation_id,
            label=label,
        ),
        occurred_at=clock.now(),
        initiative=initiative,
        outcome=outcome,
        facts=facts,
        valid_until=valid_until,
    )
