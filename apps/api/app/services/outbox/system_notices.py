"""System notices: what GAIA's own machinery tells the user, filed as notices with the facts and no words.

Every notice is named sys:{kind}:{key}, so a producer that fires twice for one occurrence files it
once. Whether, when and how the user is told is the outbox's to decide, as for any other report.
"""

from dataclasses import dataclass

from app.constants.outbox import SYSTEM_REPORT_PREFIX
from app.db.repositories.outbox_items import outbox_items_repository
from app.services.outbox.models import (
    NEEDS_YOU_OUTCOMES,
    Initiative,
    NoticeAction,
    NoticeDisplay,
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


@dataclass(frozen=True, slots=True)
class NoticeOccurrence:
    """Which occurrence of what a system notice is about, for whom, and who set it up.

    series names the recurring producer the occurrence belongs to, so its earlier tellings cover it.
    """

    user_id: str
    producer: ProducerKind
    subject_kind: SubjectKind
    kind: str
    key: str
    label: str
    initiative: Initiative = Initiative.SELF_INITIATED
    series: str | None = None


def system_notice(
    occurrence: NoticeOccurrence,
    *,
    outcome: NoticeOutcome,
    facts: list[str],
    display: str,
    action: NoticeAction | None = None,
) -> NoticeReport:
    """Return the notice that tells the user what happened, named by its kind and the occurrence's natural key.

    The facts are for the composer; display is the sentence the Updates feed shows, with the action it offers.
    """
    return NoticeReport(
        report_id=system_report_id(occurrence.kind, occurrence.key),
        recipient=occurrence.user_id,
        producer=occurrence.producer,
        subject=Subject(
            kind=occurrence.subject_kind,
            id=f"{occurrence.kind}:{occurrence.key}",
            label=occurrence.label,
            series=occurrence.series,
        ),
        occurred_at=clock.now(),
        initiative=occurrence.initiative,
        outcome=outcome,
        facts=facts,
        display=NoticeDisplay(line=display, action=action),
    )


async def settle_system_notices(user_id: str, kind: str, key_prefix: str) -> int:
    """Resolve the needs-you notices of one kind whose key starts with key_prefix: what they asked of the user is done."""
    return await outbox_items_repository.settle_with_prefix(
        user_id, system_report_id(kind, key_prefix), outcomes=NEEDS_YOU_OUTCOMES
    )
