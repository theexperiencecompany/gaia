"""A chat reply read against the paused step: the model understands it, and only what it says is done.

Real code: resolution and the handoff bridge over fakeredis; only the reply
classifier (an LLM call) is scripted.
"""

from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.constants.browser import HandoffStatus
from app.constants.chat import ConversationSource
from app.schemas.browser import NewHandoff
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.analytics_service import AnalyticsEvents
from app.services.browser import job_stop, resolution as res_mod
from app.services.browser.handoff import await_handoff, create_pending_handoff, get_handoff
from app.services.browser.job_stop import RequesterChat
from app.services.browser.jobs import (
    job_cancel_requested,
    put_job_state,
    set_job_wait,
    set_latest_job,
)
from app.services.browser.resolution import (
    HandoffReplyDecision,
    RunningTaskMessageDecision,
    resolve_handoff_from_message,
    stop_running_job_from_message,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
async def pending(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Start a job in c1 paused on handoff h1, with ARQ's pool on the same fake Redis."""
    monkeypatch.setattr(job_stop.RedisPoolManager, "get_pool", AsyncMock(return_value=fake_redis))
    await set_latest_job("c1", "job-1")
    await put_job_state(BrowserJobState(job_id="job-1", status=BrowserJobStatus.RUNNING, task="t"))
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-1",
            user_id="u1",
            conversation_id="c1",
            reason="Pay the deposit",
            reply_to="c1",
        ),
    )
    await set_job_wait("job-1", "h1")


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
    captured: list[tuple[object, ...]] = []
    monkeypatch.setattr(res_mod, "capture_event", lambda *args: captured.append(args))

    reply = await resolve_handoff_from_message("c1", "u1", "ok, paid")

    assert reply == res_mod.HandoffReply(action=action, reason="Pay the deposit")
    record = await get_handoff("h1")
    assert record is not None
    # A reply that only says done or stop carries no note on to the run.
    assert (record.status, record.message) == (status, None)
    # The user's words, read against the step it paused on, into the reply's own schema.
    schema, prompt = classify.await_args.args
    assert schema is HandoffReplyDecision
    assert "Pay the deposit" in prompt
    assert "ok, paid" in prompt
    assert classify.await_args.kwargs == {"label": "browser_handoff_conversational_resolve"}
    # A stop said in chat stops the job itself, so nothing that runs on narrates it.
    assert await job_cancel_requested("job-1") is (action == "cancel")
    # The stop is still the user deciding the handoff, attributed to them by id.
    cancelled = (
        "u1",
        AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
        {"decision": "cancel", "with_note": False},
    )
    assert captured == ([cancelled] if action == "cancel" else [])


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

    assert reply == res_mod.HandoffReply(action="unrelated", reason="Pay the deposit")
    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.PENDING


async def test_a_reply_where_nothing_waits_or_from_another_user_resolves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classify = _reads(monkeypatch, "continue")

    assert await resolve_handoff_from_message("elsewhere", "u1", "done") is None
    async with captured_wide_event() as event:
        assert await resolve_handoff_from_message("c1", "intruder", "done") is None
    [warning] = event["warnings"]
    assert "belongs to another user" in warning["msg"]
    assert (warning["browser"], warning["user_id"]) == ({"handoff_id": "h1"}, "intruder")
    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.PENDING
    assert classify.await_count == 0


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


async def test_a_reply_to_a_handoff_whose_record_expired_resolves_nothing(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    classify = _reads(monkeypatch, "continue")
    await fake_redis.delete("browser:handoff:h1")

    assert await resolve_handoff_from_message("c1", "u1", "done") is None
    classify.assert_not_awaited()


async def test_a_message_is_read_for_a_stop_only_while_a_task_runs(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    classify = AsyncMock(return_value=RunningTaskMessageDecision(action="stop"))
    monkeypatch.setattr(res_mod, "ainvoke_structured_gemini", classify)

    # No job in the chat, then one that has ended: nothing to stop, nothing read.
    assert await stop_running_job_from_message("c2", None, "stop") is False
    await set_latest_job("c2", "job-2")
    await put_job_state(BrowserJobState(job_id="job-2", status=BrowserJobStatus.DONE, task="t"))
    assert await stop_running_job_from_message("c2", None, "stop") is False
    classify.assert_not_awaited()

    assert await stop_running_job_from_message("c1", None, "stop it please") is True

    schema, prompt = classify.await_args.args
    assert schema is RunningTaskMessageDecision
    assert "stop it please" in prompt
    assert "'t'" in prompt  # the task it would stop
    assert classify.await_args.kwargs == {"label": "browser_running_task_message"}
    assert await job_cancel_requested("job-1") is True


async def test_a_plain_stop_in_the_dm_stops_the_task_the_user_started_in_a_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bot run started in a group answers to the requester's DM: "stop" there checked only the DM's slot (Greptile)."""
    monkeypatch.setattr(
        res_mod,
        "ainvoke_structured_gemini",
        AsyncMock(return_value=RunningTaskMessageDecision(action="stop")),
    )
    classify = res_mod.ainvoke_structured_gemini
    await put_job_state(
        BrowserJobState(job_id="job-g", status=BrowserJobStatus.RUNNING, task="book")
    )
    await set_latest_job("conv-group", "job-g")
    await set_latest_job("telegram:u1", "job-g")
    await put_job_state(
        BrowserJobState(job_id="job-d", status=BrowserJobStatus.RUNNING, task="read")
    )
    await set_latest_job("conv-dm", "job-d")

    stopped = await stop_running_job_from_message(
        "conv-dm", RequesterChat("u1", ConversationSource.TELEGRAM), "stop"
    )

    assert stopped is True
    assert await job_cancel_requested("job-g") is True
    assert await job_cancel_requested("job-d") is True
    # Read against every task it would stop.
    assert "'read; book'" in classify.await_args.args[1]


async def test_a_stop_said_to_one_handoff_stops_its_own_job_not_the_newest_at_the_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two of the user's runs answer at one bot chat: "stop" to job-1's prompt once stopped job-2."""
    _reads(monkeypatch, "cancel")
    await put_job_state(BrowserJobState(job_id="job-2", status=BrowserJobStatus.RUNNING, task="t"))
    await set_latest_job("c1", "job-2")

    await resolve_handoff_from_message("c1", "u1", "stop")

    assert await job_cancel_requested("job-1") is True
    assert await job_cancel_requested("job-2") is False
    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.CANCELLED
