"""Following a job's card feed: every card in order, the feed's end, and a job no worker is left to close.

Real code over fakeredis: the feed, the ending record and the slot. Only the
feed's beat is shortened, so a quiet feed is read in milliseconds, not seconds.
"""

import pytest

from app.constants.browser import BrowserSessionStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobFinished, BrowserJobRequest
from app.services.browser import job_events, job_relay
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_relay import follow_job_cards, relay_job_cards
from app.services.browser.job_stop import browser_job_task_id
from app.services.browser.jobs import claim_conversation_slot, record_ending
from tests.helpers import captured_wide_event

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

ENDED = BrowserJobFinished(
    result=BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="ok")
)


@pytest.fixture(autouse=True)
def short_beat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_events, "BROWSER_JOB_FEED_WAIT_MS", 10)


def _card(step: int) -> dict[str, object]:
    return {"tool_data": {"tool_name": "browser_task_data", "data": {"step": step}}}


class Sink:
    """The stream a follower writes to; it can act on the feed as each card arrives."""

    def __init__(self) -> None:
        self.cards: list[dict[str, object]] = []

    def __call__(self, card: dict[str, object]) -> None:
        self.cards.append(card)


async def test_every_card_reaches_the_sink_in_order_and_the_feeds_end_stops_it() -> None:
    for step in (1, 2):
        await publish_job_event("job-1", _card(step))
    await publish_job_event("job-1", JOB_TERMINAL_FRAME)
    # Never read: the feed ended before it.
    await publish_job_event("job-1", _card(9))
    sink = Sink()

    await follow_job_cards("job-1", "conv-1", sink)

    assert sink.cards == [_card(1), _card(2)]


async def test_cards_published_while_it_follows_are_read_after_the_ones_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each read resumes after the last card it saw, never from the top again."""
    await publish_job_event("job-1", _card(1))
    reads: list[str] = []
    real_read = job_events.read_job_events

    async def _read(job_id: str, cursor: str) -> list[tuple[str, dict[str, object]]]:
        reads.append(cursor)
        if len(reads) == 2:
            await publish_job_event(job_id, _card(2))
            await publish_job_event(job_id, JOB_TERMINAL_FRAME)
        return await real_read(job_id, cursor)

    monkeypatch.setattr(job_relay, "read_job_events", _read)
    sink = Sink()

    await follow_job_cards("job-1", "conv-1", sink)

    assert sink.cards == [_card(1), _card(2)]
    assert reads[0] == "0-0"
    assert reads[1] != "0-0"


async def test_a_job_that_ended_with_its_slot_free_and_its_feed_quiet_is_followed_no_more() -> None:
    """Its worker died after recording the ending: nothing will ever close the feed."""
    await publish_job_event("job-1", _card(1))
    await record_ending("job-1", ENDED)
    sink = Sink()

    async with captured_wide_event() as event:
        await follow_job_cards("job-1", "conv-1", sink)

    assert sink.cards == [_card(1)]
    [warning] = event["warnings"]
    assert (
        warning["msg"]
        == f"{LogTag.BROWSER} Browser job ended with no worker left to close its feed"
    )
    assert warning["browser"] == {"job_id": "job-1"}


@pytest.mark.parametrize("ended", [False, True])
async def test_a_job_still_running_or_still_held_by_its_worker_is_followed_to_its_feeds_end(
    monkeypatch: pytest.MonkeyPatch, ended: bool
) -> None:
    """A run sits minutes on a handoff with a quiet feed; one that just ended is still closing it."""
    if ended:
        await record_ending("job-1", ENDED)
        await claim_conversation_slot("conv-1", "job-1")
    quiet_reads = 0
    real_read = job_events.read_job_events

    async def _read(job_id: str, cursor: str) -> list[tuple[str, dict[str, object]]]:
        nonlocal quiet_reads
        events = await real_read(job_id, cursor)
        if not events:
            quiet_reads += 1
            if quiet_reads == 3:
                await publish_job_event(job_id, _card(1))
                await publish_job_event(job_id, JOB_TERMINAL_FRAME)
        return events

    monkeypatch.setattr(job_relay, "read_job_events", _read)
    sink = Sink()

    await follow_job_cards("job-1", "conv-1", sink)

    assert sink.cards == [_card(1)]
    assert quiet_reads == 3


async def test_cards_still_arriving_from_a_job_that_ended_are_all_read_before_it_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run records its ending before its last card: the follow reads until the feed is quiet."""
    await record_ending("job-1", ENDED)
    real_read = job_events.read_job_events
    published = 0

    async def _read(job_id: str, cursor: str) -> list[tuple[str, dict[str, object]]]:
        nonlocal published
        if published < 2:
            published += 1
            await publish_job_event(job_id, _card(published))
        return await real_read(job_id, cursor)

    monkeypatch.setattr(job_relay, "read_job_events", _read)
    sink = Sink()

    await follow_job_cards("job-1", "conv-1", sink)

    assert sink.cards == [_card(1), _card(2)]


REQUEST = BrowserJobRequest(
    job_id="job-1",
    tool_call_id="call-1",
    user_id="user-1",
    conversation_id="conv-1",
    task="book a table",
    in_background=True,
)
STREAM = browser_job_task_id("job-1")


class Relay:
    """The relay's stream, logged-work and stop seams, recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, opened: bool = True) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.published: list[tuple[str, dict[str, object]]] = []
        self.deltas: list[dict[str, object]] = []
        relay = self

        async def _open(stream_id: str, *, conversation_id: str, user_id: str) -> bool:
            relay.calls.append(("open", stream_id, conversation_id, user_id))
            return opened

        async def _close(stream_id: str, *, conversation_id: str, user_id: str) -> None:
            relay.calls.append(("close", stream_id, conversation_id, user_id))

        async def _stop(job_id: str) -> None:
            relay.calls.append(("stop", job_id))

        def _collect(stream_id: str, data: dict[str, object]) -> None:
            relay.published.append((stream_id, data))

        class _Deltas:
            def __init__(self, conversation_id: str, stream_id: str) -> None:
                relay.calls.append(("deltas", conversation_id, stream_id))

            def __call__(self, data: dict[str, object]) -> None:
                relay.deltas.append(data)

            async def drain(self) -> None:
                relay.calls.append(("drain",))

        monkeypatch.setattr(job_relay, "open_folded_stream", _open)
        monkeypatch.setattr(job_relay, "close_folded_stream", _close)
        monkeypatch.setattr(job_relay, "stop_job", _stop)
        monkeypatch.setattr(job_relay, "collect_frame", _collect)
        monkeypatch.setattr(job_relay, "WorkDeltas", _Deltas)


async def test_the_relay_replays_every_card_onto_its_stream_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay = Relay(monkeypatch)
    for step in (1, 2):
        await publish_job_event("job-1", _card(step))
    await publish_job_event("job-1", JOB_TERMINAL_FRAME)

    await relay_job_cards(REQUEST)

    assert relay.published == [(STREAM, _card(1)), (STREAM, _card(2))]
    assert relay.deltas == [_card(1), _card(2)]
    assert relay.calls == [
        ("open", STREAM, "conv-1", "user-1"),
        ("deltas", "conv-1", STREAM),
        ("drain",),
        ("close", STREAM, "conv-1", "user-1"),
    ]


async def test_the_relay_follows_its_own_job_in_its_own_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Relay(monkeypatch)
    followed: list[tuple[str, str]] = []

    async def follow(job_id: str, conversation_id: str, sink: object) -> None:
        followed.append((job_id, conversation_id))

    monkeypatch.setattr(job_relay, "follow_job_cards", follow)
    await relay_job_cards(REQUEST)

    assert followed == [("job-1", "conv-1")]


async def test_a_stop_that_beat_the_relay_stops_the_job_and_opens_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay = Relay(monkeypatch, opened=False)

    await relay_job_cards(REQUEST)

    assert relay.calls == [("open", STREAM, "conv-1", "user-1"), ("stop", "job-1")]
    assert relay.published == []


async def test_a_relay_that_outlives_the_feed_gives_up_and_still_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay = Relay(monkeypatch)
    monkeypatch.setattr(job_relay, "browser_job_ttl_seconds", lambda: 0.05)

    async with captured_wide_event() as event:
        await relay_job_cards(REQUEST)

    assert relay.calls[-2:] == [("drain",), ("close", STREAM, "conv-1", "user-1")]
    [warning] = event["warnings"]
    assert warning["msg"] == f"{LogTag.BROWSER} Browser job relay gave up before the job finished"
    assert warning["browser"] == {"job_id": "job-1"}
    assert event["browser"] == {"job_id": "job-1"}
