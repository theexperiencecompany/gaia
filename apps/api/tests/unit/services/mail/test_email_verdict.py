"""The email verdict reads who the user is from memory's About-the-user section, clipped, and asks without it when it cannot."""

from collections.abc import Iterator
import json
from types import SimpleNamespace

import httpx
import pytest

from app.constants.desk_buckets import EMAIL_VERDICT_PROFILE_MAX_CHARS
from app.services.mail.email_verdict import email_verdict
from app.utils.general_utils import ELLIPSIS
from app.utils.timezone import Timezone
from tests.helpers import captured_wide_event, email_verdict_answers, trigger_gate_seams

pytestmark = pytest.mark.unit

USER_ID = "507f1f77bcf86cd799439011"
EVENT = {"from": "Seed Fund <partner@seed.vc>", "subject": "Quick call about Acme?"}
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

    await email_verdict(USER_ID, "m1", EVENT, quiet=False, conversation=False)

    state = _sent_state(seams)
    assert state["user"] == ABOUT
    assert list(state) == ["user", "event", "automation"]
    seams.core.assert_awaited_once_with(USER_ID)


async def test_a_long_profile_is_clipped(seams: SimpleNamespace) -> None:
    seams.core.return_value = "## About the user\n" + "x" * (EMAIL_VERDICT_PROFILE_MAX_CHARS + 50)

    await email_verdict(USER_ID, "m1", EVENT, quiet=False, conversation=False)

    assert _sent_state(seams)["user"] == "x" * EMAIL_VERDICT_PROFILE_MAX_CHARS + ELLIPSIS


async def test_a_user_memory_knows_nothing_about_is_judged_without_a_profile(
    seams: SimpleNamespace,
) -> None:
    seams.core.return_value = "## Assistant conventions\nBe brief."

    verdict = await email_verdict(USER_ID, "m1", EVENT, quiet=False, conversation=False)

    assert verdict.bucket == "reply"
    assert list(_sent_state(seams)) == ["event", "automation"]


async def test_unreadable_memory_still_asks_and_says_why(seams: SimpleNamespace) -> None:
    seams.core.side_effect = RuntimeError("postgres down")

    async with captured_wide_event() as event:
        verdict = await email_verdict(USER_ID, "m1", EVENT, quiet=False, conversation=False)

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
