"""submit is durable; the job body validates its payload and is idempotent."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.outbox import OUTBOX_INTAKE_TASK
from app.services.outbox.intake import submit
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
)
from app.workers.tasks.outbox_tasks import outbox_intake

REPORT = NoticeReport(
    report_id="rem:1:2",
    recipient="u",
    producer=ProducerKind.REMINDER,
    subject=Subject(kind=SubjectKind.REMINDER, id="1:2", label="L"),
    occurred_at=datetime(2026, 11, 10, tzinfo=UTC),
    initiative=Initiative.USER_SCHEDULED,
    outcome=NoticeOutcome.INFO,
    facts=["x"],
)


async def test_submit_enqueues_a_job_keyed_by_the_report_id() -> None:
    pool = object()
    with (
        patch("app.services.outbox.intake.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        patch("app.services.outbox.intake.enqueue_worker_job", AsyncMock()) as enqueue,
    ):
        await submit(REPORT)

    enqueue.assert_awaited_once_with(
        pool, OUTBOX_INTAKE_TASK, REPORT.model_dump(mode="json"), _job_id="outbox:rem:1:2"
    )


async def test_a_failed_enqueue_raises_to_the_producer() -> None:
    with (
        patch("app.services.outbox.intake.RedisPoolManager.get_pool", AsyncMock()),
        patch(
            "app.services.outbox.intake.enqueue_worker_job", AsyncMock(side_effect=OSError("down"))
        ),
        pytest.raises(OSError, match="down"),
    ):
        await submit(REPORT)


async def test_the_job_parses_the_payload_into_the_report_it_was_submitted_as() -> None:
    with patch("app.workers.tasks.outbox_tasks.process_report", AsyncMock()) as process:
        await outbox_intake({}, REPORT.model_dump(mode="json"))

    process.assert_awaited_once_with(REPORT)


async def test_a_malformed_payload_raises_instead_of_being_dropped() -> None:
    with pytest.raises(ValueError):
        await outbox_intake({}, {"kind": "notice", "report_id": "x"})
