"""The email verdict: who the user is from memory, clipped, and the thread facts code knows, beside the email."""

from collections.abc import Iterator
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.constants.desk_buckets import EMAIL_VERDICT_PROFILE_MAX_CHARS, DeskBucket, Judgment
from app.constants.trigger_gates import TRIGGER_GATE_URGENT_QUESTION_KEY, UrgentChoice
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.jev_models import JevDecisionsResponse
from app.services.mail.email_verdict import (
    EmailVerdict,
    ThreadFacts,
    desk_bucket,
    email_verdict,
    read_verdict,
    verdict_request,
)
from app.services.quiet_hours_urgency import Urgency, urgent_question
from app.utils.general_utils import ELLIPSIS
from app.utils.timezone import Timezone
from tests.helpers import captured_wide_event, email_verdict_answers, trigger_gate_seams

pytestmark = pytest.mark.unit

USER_ID = "507f1f77bcf86cd799439011"
EMAIL = {"from": {"name": "Seed Fund", "address": "partner@seed.vc"}, "subject": "Quick call?"}
ABOUT = "Founder and CEO of Acme, an AI inbox assistant. Raising a seed round this quarter."


@pytest.fixture
def seams() -> Iterator[SimpleNamespace]:
    with trigger_gate_seams(Timezone.parse("Asia/Kolkata")) as seams:
        seams.jev.mock(return_value=httpx.Response(200, json=email_verdict_answers("reply")))
        yield seams


def _sent_state(seams: SimpleNamespace) -> dict[str, object]:
    state: dict[str, object] = json.loads(seams.jev.calls.last.request.content)["state"]
    return state


async def test_the_user_jev_judges_for_rides_ahead_of_the_email(seams: SimpleNamespace) -> None:
    seams.core.return_value = f"## About the user\n{ABOUT}\n\n## Assistant conventions\nBe brief."

    await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=False)

    state = _sent_state(seams)
    assert state == {"user": {"profile": ABOUT}, "email": EMAIL}
    seams.core.assert_awaited_once_with(USER_ID)


async def test_a_long_profile_is_clipped(seams: SimpleNamespace) -> None:
    seams.core.return_value = "## About the user\n" + "x" * (EMAIL_VERDICT_PROFILE_MAX_CHARS + 50)

    await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=False)

    assert _sent_state(seams)["user"] == {
        "profile": "x" * EMAIL_VERDICT_PROFILE_MAX_CHARS + ELLIPSIS
    }


async def test_a_user_memory_knows_nothing_about_is_judged_without_a_profile(
    seams: SimpleNamespace,
) -> None:
    seams.core.return_value = "## Assistant conventions\nBe brief."

    verdict = await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=False)

    assert verdict.bucket == "reply"
    assert list(_sent_state(seams)) == ["email"]


async def test_unreadable_memory_still_asks_and_says_why(seams: SimpleNamespace) -> None:
    seams.core.side_effect = RuntimeError("postgres down")

    async with captured_wide_event() as event:
        verdict = await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=False)

    assert verdict.bucket == "reply"
    assert "user" not in _sent_state(seams)
    warnings = event.get("warnings", [])
    assert isinstance(warnings, list)
    assert [w for w in warnings if w["msg"] == "email_verdict.profile_unreadable"] == [
        {
            "msg": "email_verdict.profile_unreadable",
            "error": "postgres down",
            "error_type": "RuntimeError",
        }
    ]


async def test_a_conversation_by_day_is_reply_kept_without_asking_jev(
    seams: SimpleNamespace,
) -> None:
    thread = ThreadFacts(user_wrote_in_thread=True, latest_from_other=True)

    verdict = await email_verdict(USER_ID, "m1", EMAIL, thread=thread, quiet=False)

    assert (verdict.bucket, verdict.skips) == (DeskBucket.REPLY, False)
    assert seams.jev.call_count == 0
    assert seams.verdicts.kept[USER_ID, "m1"].answers == {}


async def test_a_thread_the_user_wrote_last_in_is_asked_with_its_facts(
    seams: SimpleNamespace,
) -> None:
    thread = ThreadFacts(user_wrote_in_thread=True, latest_from_other=False)

    verdict = await email_verdict(USER_ID, "m1", EMAIL, thread=thread, quiet=False)

    assert verdict.bucket == DeskBucket.REPLY
    assert _sent_state(seams)["thread"] == {
        "user_wrote_in_thread": True,
        "latest_from_other": False,
    }


def _body(bucket: str, *, can_wait: float = 1.0) -> JevDecisionsResponse:
    return JevDecisionsResponse.model_validate(email_verdict_answers(bucket, can_wait=can_wait))


def test_a_by_day_verdict_reads_the_table_not_a_conversation() -> None:
    assert read_verdict(_body("act"), quiet=False).bucket is DeskBucket.ACT


def test_quiet_hours_keeps_the_urgency_and_by_day_does_not() -> None:
    body = _body("reply", can_wait=0.2)

    assert read_verdict(body, quiet=True).urgency == Urgency(
        probability=0.8, choice=UrgentChoice.MEETING
    )
    assert read_verdict(body, quiet=False).urgency is None


def test_quiet_hours_asks_the_urgent_question_itself() -> None:
    _, by_day = verdict_request(EMAIL, thread=None, quiet=False, profile="")
    _, quiet = verdict_request(EMAIL, thread=None, quiet=True, profile="")

    assert TRIGGER_GATE_URGENT_QUESTION_KEY not in by_day
    assert quiet[TRIGGER_GATE_URGENT_QUESTION_KEY] == urgent_question()


async def test_an_unreadable_memory_error_is_clipped_to_the_wides_event(
    seams: SimpleNamespace,
) -> None:
    seams.core.side_effect = RuntimeError("x" * 400)

    async with captured_wide_event() as event:
        await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=False)

    (warning,) = [w for w in event["warnings"] if w["msg"] == "email_verdict.profile_unreadable"]
    assert warning["error"] == "x" * 300


async def test_a_quiet_hours_ask_rides_the_urgent_question_and_keeps_what_it_said(
    seams: SimpleNamespace,
) -> None:
    seams.jev.mock(
        return_value=httpx.Response(200, json=email_verdict_answers("reply", can_wait=0.2))
    )

    with patch("shared.py.wide_events._loguru") as loguru:
        verdict = await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=True)

    questions = json.loads(seams.jev.calls.last.request.content)["questions"]
    assert questions[TRIGGER_GATE_URGENT_QUESTION_KEY] == urgent_question()
    assert verdict.urgency == Urgency(probability=0.8, choice=UrgentChoice.MEETING)
    assert seams.verdicts.kept[USER_ID, "m1"].urgency == verdict.urgency
    assert loguru.opt.return_value.bind.call_args.kwargs["message_id"] == "m1"


async def test_a_kept_verdict_with_its_urgency_answers_a_quiet_hours_ask(
    seams: SimpleNamespace,
) -> None:
    urgency = Urgency(probability=0.9, choice=UrgentChoice.MEETING)
    seams.verdicts.kept[USER_ID, "m1"] = EmailVerdictDocument(
        user_id=USER_ID,
        message_id="m1",
        answers={Judgment.IS_PERSON: 0.1},
        bucket=DeskBucket.FYI,
        urgency=urgency,
    )

    verdict = await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=True)

    assert (verdict.bucket, verdict.urgency) == (DeskBucket.FYI, urgency)
    assert seams.jev.call_count == 0


async def test_a_kept_verdict_without_its_urgency_is_asked_again_in_quiet_hours(
    seams: SimpleNamespace,
) -> None:
    seams.verdicts.kept[USER_ID, "m1"] = EmailVerdictDocument(
        user_id=USER_ID,
        message_id="m1",
        answers={Judgment.IS_PERSON: 0.1},
        bucket=DeskBucket.FYI,
    )
    seams.jev.mock(
        return_value=httpx.Response(200, json=email_verdict_answers("reply", can_wait=0.2))
    )

    verdict = await email_verdict(USER_ID, "m1", EMAIL, thread=None, quiet=True)

    assert seams.jev.call_count == 1
    assert verdict.urgency is not None
    assert seams.verdicts.kept[USER_ID, "m1"].urgency == verdict.urgency


def _answers(**overrides: float) -> dict[Judgment, float]:
    answers: dict[Judgment, float] = {
        Judgment.IS_PERSON: 0.05,
        Judgment.ASKS_USER: 0.05,
        Judgment.REPORTS_ISSUE: 0.05,
        Judgment.OFFICIAL: 0.05,
        Judgment.RELEVANT: 0.05,
        Judgment.BULK: 0.05,
    }
    answers.update({Judgment(k): p for k, p in overrides.items()})
    return answers


def _verdict(**overrides: float) -> EmailVerdict:
    answers = _answers(**overrides)
    return EmailVerdict(answers=answers, bucket=desk_bucket(answers, conversation=False))


def test_bulk_mail_from_a_person_about_the_users_work_is_not_noise() -> None:
    verdict = _verdict(is_person=0.95, relevant=0.9, bulk=0.95)

    assert verdict.bucket is DeskBucket.FYI
    assert verdict.skips is False


def test_bulk_mail_from_a_person_on_another_topic_is_junk() -> None:
    verdict = _verdict(is_person=0.95, relevant=0.05, bulk=0.95)

    assert (verdict.bucket, verdict.skips) == (DeskBucket.JUNK, True)
