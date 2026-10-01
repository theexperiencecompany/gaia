"""A chat reply read against the paused step: the model understands it, and only what it says is done.

Real code: resolution and the handoff bridge over fakeredis; only the reply
classifier (an LLM call) is scripted.
"""

from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.constants.browser import HandoffStatus
from app.services.browser import resolution as res_mod
from app.services.browser.handoff import await_handoff, create_pending_handoff, get_handoff
from app.services.browser.resolution import HandoffReplyDecision, resolve_handoff_from_message

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
async def pending(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await create_pending_handoff("h1", "u1", "c1", "Pay the deposit", reply_to="c1")


def _reads(monkeypatch: pytest.MonkeyPatch, action: str, note: str | None = None) -> AsyncMock:
    classify = AsyncMock(return_value=HandoffReplyDecision(action=action, note=note))
    monkeypatch.setattr(res_mod, "ainvoke_structured_gemini", classify)
    return classify


@pytest.mark.parametrize(
    ("action", "status"),
    [("continue", HandoffStatus.COMPLETED), ("cancel", HandoffStatus.CANCELLED)],
)
async def test_a_reply_the_model_reads_as_done_or_stop_settles_the_handoff(
    monkeypatch: pytest.MonkeyPatch, action: str, status: HandoffStatus
) -> None:
    classify = _reads(monkeypatch, action)

    reply = await resolve_handoff_from_message("c1", "u1", "ok")

    assert reply == res_mod.HandoffReply(action=action, reason="Pay the deposit")
    record = await get_handoff("h1")
    assert record is not None
    assert record.status is status
    # Read against the step it paused on, not in the abstract.
    assert "Pay the deposit" in classify.await_args.args[1]


async def test_only_a_reply_the_model_calls_a_redirect_reaches_the_run_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reads(monkeypatch, "redirect", "  just read me the total  ")

    await resolve_handoff_from_message("c1", "u1", "forget paying, read me the total")

    outcome = await await_handoff("h1", timeout_seconds=1)
    assert (outcome.status, outcome.message, outcome.redirect) == (
        HandoffStatus.COMPLETED,
        "just read me the total",
        True,
    )


async def test_a_note_sent_with_a_done_is_passed_on_but_is_no_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reads(monkeypatch, "continue", "the small one")

    await resolve_handoff_from_message("c1", "u1", "done, get the small one")

    outcome = await await_handoff("h1", timeout_seconds=1)
    assert (outcome.message, outcome.redirect) == ("the small one", False)


async def test_an_unrelated_reply_leaves_the_handoff_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reads(monkeypatch, "unrelated")

    reply = await resolve_handoff_from_message("c1", "u1", "which password?")

    assert reply is not None
    assert reply.action == "unrelated"
    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.PENDING


async def test_a_reply_where_nothing_waits_or_from_another_user_resolves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classify = _reads(monkeypatch, "continue")

    assert await resolve_handoff_from_message("elsewhere", "u1", "done") is None
    assert await resolve_handoff_from_message("c1", "intruder", "done") is None
    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.PENDING
    assert classify.await_count == 1


async def test_a_classifier_failure_reaches_the_turn_and_leaves_the_handoff_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        res_mod, "ainvoke_structured_gemini", AsyncMock(side_effect=RuntimeError("model down"))
    )

    with pytest.raises(RuntimeError):
        await resolve_handoff_from_message("c1", "u1", "done")

    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.PENDING
