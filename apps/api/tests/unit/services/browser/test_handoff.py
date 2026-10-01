"""The Redis handoff bridge: one decision of record, its owner, and a wait that wakes on it."""

import asyncio

import fakeredis.aioredis
import pytest

from app.constants.browser import EngineFailure, HandoffDecision, HandoffKind, HandoffStatus
from app.constants.chat import ConversationSource
from app.schemas.browser import HandoffRecord
from app.services.analytics_service import AnalyticsEvents
from app.services.browser import handoff as handoff_mod
from app.services.browser.exceptions import BrowserHandoffNotOwned, BrowserUnavailableError
from app.services.browser.live_code import mint_live_code, resolve_live_code

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def redis(fake_redis: fakeredis.aioredis.FakeRedis) -> fakeredis.aioredis.FakeRedis:
    return fake_redis


@pytest.fixture(autouse=True)
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(handoff_mod, "capture_event", lambda *args: calls.append(args))
    return calls


async def test_the_first_decision_is_the_one_of_record(events: list[tuple[object, ...]]) -> None:
    """Card, chat reply and a stop can all reach one handoff; only the first decides it, and a late one hears that decision."""
    await handoff_mod.create_pending_handoff("h1", "user-1", "conv-1", reply_to="conv-1")

    first = await handoff_mod.resolve_handoff("h1", HandoffDecision.CANCEL, "user-1", "first")
    second = await handoff_mod.resolve_handoff("h1", HandoffDecision.CONTINUE, "user-1", "second")

    record = await handoff_mod.get_handoff("h1")
    assert (first, second) == (HandoffStatus.CANCELLED, HandoffStatus.CANCELLED)
    assert record is not None
    assert (record.status, record.message) == (HandoffStatus.CANCELLED, "first")
    # Resolution can run where no request context exists: the id travels explicitly.
    assert events == [
        (
            "user-1",
            AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
            {"decision": "cancel", "with_note": True},
        )
    ]


async def test_only_its_owner_decides_a_handoff() -> None:
    await handoff_mod.create_pending_handoff("h2", "owner", "conv-2")

    with pytest.raises(BrowserHandoffNotOwned):
        await handoff_mod.resolve_handoff("h2", HandoffDecision.CONTINUE, "intruder")
    assert await handoff_mod.resolve_handoff("gone", HandoffDecision.CONTINUE, "owner") is None


async def test_the_wait_wakes_on_the_decision_with_its_note_and_redirect() -> None:
    """The waiting run is woken by the settle itself, an hour-long window notwithstanding, and gets the note it was sent with."""
    await handoff_mod.create_pending_handoff("h3", "user-1", "conv-3", reply_to="conv-3")
    waiter = asyncio.create_task(handoff_mod.await_handoff("h3", timeout_seconds=3600))
    await asyncio.sleep(0)

    await handoff_mod.resolve_handoff(
        "h3", HandoffDecision.CONTINUE, "user-1", " open Contact ", redirect=True
    )

    outcome = await asyncio.wait_for(waiter, timeout=2)
    assert (outcome.status, outcome.message, outcome.redirect) == (
        HandoffStatus.COMPLETED,
        "open Contact",
        True,
    )
    assert await handoff_mod.get_pending_handoff_for_reply("conv-3") is None


async def test_a_lapsed_wait_settles_timeout_and_a_later_decision_is_late() -> None:
    """The run gave up; a continue now must not read as accepted, nor leave the chat looking paused."""
    await handoff_mod.create_pending_handoff("h4", "user-1", "conv-4", reply_to="conv-4")

    outcome = await handoff_mod.await_handoff("h4", timeout_seconds=0.05)
    late = await handoff_mod.resolve_handoff("h4", HandoffDecision.CONTINUE, "user-1", "go on")

    assert outcome.status is HandoffStatus.TIMEOUT
    assert late is HandoffStatus.TIMEOUT
    assert await handoff_mod.get_pending_handoff_for_reply("conv-4") is None


async def test_a_stop_and_a_lost_browser_settle_it_and_close_its_live_link() -> None:
    """Settled, nobody is to act in that browser any more: its bot link stops opening it."""
    await handoff_mod.create_pending_handoff("h5", "user-1", "conv-5")
    code = await mint_live_code("sess-5", "user-1", "h5")
    await handoff_mod.create_pending_handoff("h6", "user-1", "conv-6")

    assert await handoff_mod.cancel_handoff("h5") is HandoffStatus.CANCELLED
    assert await handoff_mod.fail_handoff("h6", EngineFailure.SESSION_GONE) is HandoffStatus.FAILED
    assert await resolve_live_code(code) is None
    outcome = await handoff_mod.await_handoff("h6", timeout_seconds=1)
    assert (outcome.status, outcome.cause) == (HandoffStatus.FAILED, EngineFailure.SESSION_GONE)


async def test_an_agent_pause_never_takes_a_reply_address() -> None:
    """A reply address makes the user's next chat message resolve the handoff; they were never asked about an agent pause."""
    await handoff_mod.create_pending_handoff(
        "h7", "user-1", "conv-7", "stuck", kind=HandoffKind.AGENT, reply_to="conv-7"
    )

    assert await handoff_mod.get_pending_handoff_for_reply("conv-7") is None


def test_a_bot_runs_reply_comes_from_the_users_chat_on_that_platform() -> None:
    """The prompt goes to the requester's DM whichever chat started the run, so a group's run is answered from there."""
    assert (
        handoff_mod.reply_address("group", "user-1", ConversationSource.DISCORD) == "discord:user-1"
    )
    assert handoff_mod.reply_address("conv-web", "user-1", ConversationSource.WEB) == "conv-web"
    assert handoff_mod.reply_address("conv-web", "user-1", None) == "conv-web"


async def test_a_handoff_that_was_never_stored_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handoff nobody can read back would stall the run for its whole window instead of failing now."""

    async def _write_fails(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(handoff_mod.redis_cache, "set", _write_fails)
    with pytest.raises(BrowserUnavailableError):
        await handoff_mod.create_pending_handoff("h8", "user-1", "conv-8")


def test_a_record_written_before_reply_addresses_still_parses() -> None:
    record = HandoffRecord.model_validate(
        {"status": "pending", "user_id": "user-1", "conversation_id": "conv-old"}
    )
    assert (record.kind, record.reply_address) == (HandoffKind.USER, "")
