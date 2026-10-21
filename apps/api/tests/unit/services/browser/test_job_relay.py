"""Following a job's card feed: every card in order, the feed's end, and a job no worker is left to close.

Real code over fakeredis: the feed, the ending record and the slot. Only the
feed's beat is shortened, so a quiet feed is read in milliseconds, not seconds.
"""

import pytest

from app.constants.browser import BrowserSessionStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobFinished
from app.services.browser import job_events, job_relay
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_relay import follow_job_cards
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

    async def __call__(self, card: dict[str, object]) -> None:
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
    real_read = job_relay.read_job_events

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
    real_read = job_relay.read_job_events

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
    real_read = job_relay.read_job_events
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
