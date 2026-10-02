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
from tests.helpers import captured_wide_event

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
    await handoff_mod.create_pending_handoff(
        "h1", "user-1", "conv-1", reply_to="conv-1", job_id="job-1"
    )

    first = await handoff_mod.resolve_handoff("h1", HandoffDecision.CANCEL, "user-1", "first")
    second = await handoff_mod.resolve_handoff("h1", HandoffDecision.CONTINUE, "user-1", "second")

    record = await handoff_mod.get_handoff("h1")
    assert (first, second) == (HandoffStatus.CANCELLED, HandoffStatus.CANCELLED)
    assert record is not None
    assert (record.status, record.message) == (HandoffStatus.CANCELLED, "first")
    # A plain note is the user's words, never a replaced request.
    assert (await handoff_mod.await_handoff("h1", timeout_seconds=1)).redirect is False
    # Resolution can run where no request context exists: the id travels explicitly.
    assert events == [
        (
            "user-1",
            AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
            {"decision": "cancel", "with_note": True},
        )
    ]


async def test_only_its_owner_decides_a_handoff() -> None:
    await handoff_mod.create_pending_handoff("h2", "owner", "conv-2", job_id="job-1")

    with pytest.raises(BrowserHandoffNotOwned, match="^Not authorized to resolve this handoff$"):
        await handoff_mod.resolve_handoff("h2", HandoffDecision.CONTINUE, "intruder")
    async with captured_wide_event() as event:
        assert await handoff_mod.resolve_handoff("gone", HandoffDecision.CONTINUE, "owner") is None
    [warning] = event["warnings"]
    assert "Handoff decision dropped" in warning["msg"]
    assert warning["handoff_id"] == "gone"


async def test_a_bare_continue_carries_no_note_and_a_bare_handoff_no_reason_or_address(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await handoff_mod.create_pending_handoff("h2b", "user-1", "conv-2b", job_id="job-1")
    assert await redis.keys("browser:handoff:reply:*") == []

    await handoff_mod.resolve_handoff("h2b", HandoffDecision.CONTINUE, "user-1")

    record = await handoff_mod.get_handoff("h2b")
    assert record is not None
    assert (record.reason, record.message) == ("", None)
    assert await redis.keys("browser:handoff:reply:*") == []


async def test_the_wait_wakes_on_the_decision_with_its_note_and_redirect() -> None:
    """The waiting run is woken by the settle itself, an hour-long window notwithstanding, and gets the note it was sent with."""
    await handoff_mod.create_pending_handoff(
        "h3", "user-1", "conv-3", reply_to="conv-3", job_id="job-1"
    )
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
    await handoff_mod.create_pending_handoff(
        "h4", "user-1", "conv-4", reply_to="conv-4", job_id="job-1"
    )

    async with captured_wide_event() as event:
        outcome = await handoff_mod.await_handoff("h4", timeout_seconds=0.05)
    late = await handoff_mod.resolve_handoff("h4", HandoffDecision.CONTINUE, "user-1", "go on")

    [warning] = event["warnings"]
    assert "timed out" in warning["msg"]
    assert (warning["handoff_id"], warning["timeout_seconds"]) == ("h4", 0.05)
    assert outcome.status is HandoffStatus.TIMEOUT
    assert late is HandoffStatus.TIMEOUT
    assert await handoff_mod.get_pending_handoff_for_reply("conv-4") is None


async def test_a_stop_and_a_lost_browser_settle_it_and_close_its_live_link() -> None:
    """Settled, nobody is to act in that browser any more: its bot link stops opening it."""
    await handoff_mod.create_pending_handoff("h5", "user-1", "conv-5", job_id="job-1")
    code = await mint_live_code("sess-5", "user-1", "h5")
    await handoff_mod.create_pending_handoff("h6", "user-1", "conv-6", job_id="job-1")

    assert await handoff_mod.cancel_handoff("h5") is HandoffStatus.CANCELLED
    assert await handoff_mod.fail_handoff("h6", EngineFailure.SESSION_GONE) is HandoffStatus.FAILED
    assert await resolve_live_code(code) is None
    async with captured_wide_event() as event:
        outcome = await handoff_mod.await_handoff("h6", timeout_seconds=1)
    assert (outcome.status, outcome.cause) == (HandoffStatus.FAILED, EngineFailure.SESSION_GONE)
    # A decision, not a lapse: nothing timed out.
    assert event.get("warnings", []) == []
    # The decision of record stands against a later settle.
    assert await handoff_mod.cancel_handoff("h6") is HandoffStatus.FAILED


async def test_settling_an_older_handoff_leaves_a_newer_ones_reply_address() -> None:
    """A bot address is shared by the user's runs: the older run ending must not deafen the newer one's prompt."""
    await handoff_mod.create_pending_handoff(
        "old", "user-1", "conv-a", reply_to="telegram:user-1", job_id="job-1"
    )
    await handoff_mod.create_pending_handoff(
        "new", "user-1", "conv-b", reply_to="telegram:user-1", job_id="job-1"
    )

    await handoff_mod.cancel_handoff("old")

    assert await handoff_mod.get_pending_handoff_for_reply("telegram:user-1") == "new"


async def test_a_stop_on_a_handoff_whose_record_already_expired_still_settles() -> None:
    assert await handoff_mod.cancel_handoff("expired") is HandoffStatus.CANCELLED


async def test_everything_a_handoff_writes_lapses_with_the_job(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await handoff_mod.create_pending_handoff(
        "h9", "user-1", "conv-9", reply_to="conv-9", job_id="job-1"
    )
    reply_ttl = await redis.ttl("browser:handoff:reply:conv-9")

    await handoff_mod.resolve_handoff("h9", HandoffDecision.CONTINUE, "user-1")

    assert reply_ttl > 0
    keys = await redis.keys("browser:handoff:h9*")
    assert sorted(keys) == [
        "browser:handoff:h9",
        "browser:handoff:h9:settled",
        "browser:handoff:h9:wake",
    ]
    # Each as long as the job can live, not the cache's default hour.
    assert all([await redis.ttl(key) > 3600 for key in keys])


async def test_an_agent_pause_never_takes_a_reply_address(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A reply address makes the user's next chat message resolve the handoff; they were never asked about an agent pause."""
    await handoff_mod.create_pending_handoff(
        "h7", "user-1", "conv-7", "stuck", kind=HandoffKind.AGENT, reply_to="conv-7", job_id="job-1"
    )

    assert await handoff_mod.get_pending_handoff_for_reply("conv-7") is None
    assert await redis.keys("browser:handoff:reply:*") == []


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
    with pytest.raises(
        BrowserUnavailableError, match=r"^Could not persist handoff h8 \(storage unavailable\)\.$"
    ):
        await handoff_mod.create_pending_handoff("h8", "user-1", "conv-8", job_id="job-1")


async def test_a_decision_whose_marker_never_landed_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Told the decision was taken when it was never stored, the run would wait out its window."""
    await handoff_mod.create_pending_handoff("h10", "user-1", "conv-10", job_id="job-1")

    async def _write_fails(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(handoff_mod.redis_cache, "set_if_absent", _write_fails)
    with pytest.raises(BrowserUnavailableError, match="h10"):
        await handoff_mod.cancel_handoff("h10")


def test_a_record_written_before_reply_addresses_still_parses() -> None:
    record = HandoffRecord.model_validate(
        {"status": "pending", "user_id": "user-1", "conversation_id": "conv-old", "job_id": "job-1"}
    )
    assert (record.kind, record.reply_address) == (HandoffKind.USER, "")
