"""Hermetic unit tests for EmailVerdictsRepository: the key, the update document, and the retry.

Real-Mongo proof belongs in the contracts tier; this tier pins what keep hands the driver —
the JSON-mode update that also stores the urgency, the fresh TTL anchor, and the one retry that
overwrites the winner of a racing first insert.
"""

from datetime import UTC
from unittest.mock import AsyncMock, patch

from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.desk_buckets import DeskBucket, Judgment
from app.constants.trigger_gates import UrgentChoice
from app.db.repositories.email_verdicts import EmailVerdictsRepository
from app.models.email_verdict_models import EmailVerdictDocument
from app.services.quiet_hours_urgency import Urgency

pytestmark = pytest.mark.unit

USER = "6812f0b3c9a14e2b7d5a91cc"
KEY = {"user_id": USER, "message_id": "m1"}


def _verdict() -> EmailVerdictDocument:
    return EmailVerdictDocument(
        user_id=USER,
        message_id="m1",
        answers={Judgment.REPORTS_ISSUE: 0.9, Judgment.IS_PERSON: 0.1},
        bucket=DeskBucket.ACT,
        urgency=Urgency(probability=0.9, choice=UrgentChoice.MEETING),
    )


async def test_keep_writes_the_verdict_its_urgency_and_a_fresh_utc_anchor() -> None:
    apply = AsyncMock()
    with patch.object(EmailVerdictsRepository, "_apply_raw_update", apply):
        await EmailVerdictsRepository().keep(_verdict())

    (written,) = apply.call_args_list
    assert written.args[0] == KEY
    update = written.args[1]["$set"]
    assert {k: v for k, v in update.items() if k != "created_at"} == {
        "answers": {"reports_issue": 0.9, "is_person": 0.1},
        "bucket": "act",
        "urgency": {"probability": 0.9, "choice": "meeting"},
    }
    assert update["created_at"].tzinfo is UTC
    # mode="json" is what stores plain strings; python mode keeps the enums, which Mongo
    # cannot encode and a reader would have to guess at.
    assert type(update["bucket"]) is str
    assert all(type(judgment) is str for judgment in update["answers"])
    assert written.kwargs == {"upsert": True}


async def test_a_duplicate_key_retries_the_same_upsert_once() -> None:
    apply = AsyncMock(side_effect=[DuplicateKeyError("dup"), None])
    with patch.object(EmailVerdictsRepository, "_apply_raw_update", apply):
        await EmailVerdictsRepository().keep(_verdict())

    first, second = apply.call_args_list
    assert first == second
    assert first.args[0] == KEY
    assert first.args[1]["$set"]["urgency"] == {"probability": 0.9, "choice": "meeting"}
    assert first.kwargs == {"upsert": True}
