"""The resume verdict: can a reloading client re-attach to an in-flight turn?

``get_resumable_stream_id`` is the authoritative answer. ``conversation_service``
exposes it as ``active_stream_id``, and the web client treats it as final: on a
null verdict ``turnManager`` runs ``markDeadSendsFailed`` and the user's own
message flips to FAILED. A wrong answer in either direction is user-visible —
a false null kills a live turn's tab, a false positive attaches the client to a
dead stream.

Redis is real (fakeredis) rather than mocked because TTL expiry *is* the
behaviour under test; a mocked client would happily report whatever the test
told it to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest

from app.constants.cache import (
    STREAM_ACTIVE_PREFIX,
    STREAM_EVENTS_PREFIX,
    STREAM_PROGRESS_PREFIX,
    STREAM_TTL,
)
from app.core.stream_manager import StreamManager
from app.db.redis import redis_cache

SID = "stream-long-turn"
CONV = "conv-1"
USER = "user-1"

ACTIVE_KEY = f"{STREAM_ACTIVE_PREFIX}{USER}:{CONV}"
PROGRESS_KEY = f"{STREAM_PROGRESS_PREFIX}{SID}"
EVENTS_KEY = f"{STREAM_EVENTS_PREFIX}{SID}"

#: Seconds left on the turn's keys after it has been running a while. Any value
#: below STREAM_TTL works; this one just has to be distinguishable from a refresh.
NEARLY_EXPIRED = 30


@pytest.fixture(autouse=True)
async def fake_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Patch the module singleton so every layer below sees one real Redis."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.flushall()
    await client.connection_pool.disconnect()


async def _age_the_turns_keys(client: fakeredis.aioredis.FakeRedis) -> None:
    """Wind every key of a running turn down to almost-expired.

    Stands in for wall-clock time: a turn that has been running for most of
    STREAM_TTL. Real turns reach this routinely — EXECUTOR_WAIT_TIMEOUT is 30
    minutes and BASH_MAX_TIMEOUT_SECONDS is 1800, against a 5-minute STREAM_TTL.
    """
    for key in (ACTIVE_KEY, PROGRESS_KEY, EVENTS_KEY):
        if await client.exists(key):
            await client.expire(key, NEARLY_EXPIRED)


async def _keep_streaming() -> None:
    """One more chunk of a turn that is still very much alive."""
    await StreamManager.update_progress(SID, "still working ")
    await StreamManager.publish_chunk(SID, 'data: {"response": "still working "}\n\n')


async def _keep_streaming_from_the_executor() -> None:
    """One more frame from a turn that has handed off to the executor.

    Once comms says "I'm on it" the turn parks in ``await_executor_done`` and
    every later frame comes from the executor's Redis writer, which only
    publishes — ``update_progress`` is a comms-loop call and stops firing. This
    is what a long turn actually looks like for most of its life.
    """
    await StreamManager.publish_chunk(SID, 'data: {"tool": "bash", "status": "running"}\n\n')


class TestActiveIndexLifetime:
    async def test_ongoing_activity_keeps_a_long_turn_resumable(self, fake_redis):
        """A turn that is still streaming must not become unresumable.

        The reverse index is what a reloading client rediscovers the turn
        through. If it expires under a running turn, the backend reports "no
        turn is running" for a turn that is running, and the user watches their
        own message flip to FAILED while the agent is still working.
        """
        await StreamManager.start_stream(SID, CONV, USER)
        await _age_the_turns_keys(fake_redis)

        await _keep_streaming()

        assert await fake_redis.ttl(ACTIVE_KEY) > NEARLY_EXPIRED, (
            "the resume index was not refreshed by ongoing activity, so a turn "
            "that outlives STREAM_TTL becomes unresumable while still running"
        )

    async def test_the_same_activity_refreshes_the_other_two_keys(self, fake_redis):
        """Control. Without it, the assertion above could be inventing a rule
        rather than pointing at an inconsistency: activity already refreshes the
        turn's other two keys, and the index is the one that misses out.
        """
        await StreamManager.start_stream(SID, CONV, USER)
        await _age_the_turns_keys(fake_redis)

        await _keep_streaming()

        assert await fake_redis.ttl(PROGRESS_KEY) > NEARLY_EXPIRED
        assert await fake_redis.ttl(EVENTS_KEY) > NEARLY_EXPIRED

    async def test_executor_frames_keep_a_long_turn_resumable(self, fake_redis):
        """A turn producing only executor frames must stay resumable.

        EXECUTOR_WAIT_TIMEOUT is 30 minutes against a 5-minute STREAM_TTL, so
        any executor turn past 5 minutes reaches this. The user reloads, the
        backend says no turn is running, and their own message flips to FAILED
        while the agent is still working.
        """
        await StreamManager.start_stream(SID, CONV, USER)
        await _age_the_turns_keys(fake_redis)

        await _keep_streaming_from_the_executor()

        assert await fake_redis.ttl(ACTIVE_KEY) > NEARLY_EXPIRED, (
            "an executor-only turn did not refresh its resume index, so it becomes "
            "unresumable while still running and the user's message flips to FAILED"
        )

    async def test_executor_frames_keep_a_long_turn_cancellable(self, fake_redis):
        """The stop button must keep working on a long turn.

        ``cancel_stream_endpoint`` short-circuits on a missing progress key and
        returns "Stream not found" WITHOUT setting the cancel signal, so an
        expired progress key makes the button silently do nothing while the
        executor runs to completion and posts its result anyway.
        """
        await StreamManager.start_stream(SID, CONV, USER)
        await _age_the_turns_keys(fake_redis)

        await _keep_streaming_from_the_executor()

        assert await fake_redis.ttl(PROGRESS_KEY) > NEARLY_EXPIRED, (
            "an executor-only turn did not refresh its progress key, so once it "
            "expires cancel_stream_endpoint returns 'Stream not found' and never "
            "sets the cancel signal — the stop button silently does nothing"
        )

    async def test_a_refreshed_index_still_points_at_the_same_stream(self, fake_redis):
        """Refreshing the TTL must not disturb the value — an index rewritten
        with the wrong stream id would attach the client to another turn."""
        await StreamManager.start_stream(SID, CONV, USER)
        await _age_the_turns_keys(fake_redis)

        await _keep_streaming()

        assert await StreamManager.get_resumable_stream_id(USER, CONV) == SID

    async def test_a_finished_turn_does_not_get_its_index_revived(self, fake_redis):
        """``complete_stream`` clears the index on purpose. A blanket refresh in
        the wrong place would resurrect it and hand a reloading client a stream
        that has already sent [DONE]."""
        await StreamManager.start_stream(SID, CONV, USER)
        await StreamManager.complete_stream(SID)

        await StreamManager.update_progress(SID, "late straggler chunk")

        assert await fake_redis.exists(ACTIVE_KEY) == 0
        assert await StreamManager.get_resumable_stream_id(USER, CONV) is None


class TestResumeVerdict:
    """The five branches of ``get_resumable_stream_id``. It had no direct test —
    every existing reference mocks it — which is how a live turn could start
    reporting itself idle without anything going red.
    """

    async def test_an_idle_conversation_is_not_resumable(self, fake_redis):
        assert await StreamManager.get_resumable_stream_id(USER, CONV) is None

    async def test_a_live_turn_is_resumable(self, fake_redis):
        await StreamManager.start_stream(SID, CONV, USER)

        assert await StreamManager.get_resumable_stream_id(USER, CONV) == SID

    async def test_an_indexed_turn_with_no_progress_is_not_resumable(self, fake_redis):
        """The progress key outlives nothing — if it is gone there is no turn to
        rebuild, so the index alone must not be trusted."""
        await StreamManager.start_stream(SID, CONV, USER)
        await fake_redis.delete(PROGRESS_KEY)

        assert await StreamManager.get_resumable_stream_id(USER, CONV) is None

    async def test_a_completed_turn_is_not_resumable(self, fake_redis):
        await StreamManager.start_stream(SID, CONV, USER)
        await StreamManager.complete_stream(SID)

        assert await StreamManager.get_resumable_stream_id(USER, CONV) is None

    async def test_a_cancelled_turn_is_not_resumable(self, fake_redis):
        await StreamManager.start_stream(SID, CONV, USER)
        await StreamManager.cancel_stream(SID)

        assert await StreamManager.get_resumable_stream_id(USER, CONV) is None

    async def test_one_users_turn_is_not_visible_to_another(self, fake_redis):
        """The index is keyed by user AND conversation; a lookup that ignored the
        user would hand someone else's in-flight stream to the wrong account."""
        await StreamManager.start_stream(SID, CONV, USER)

        assert await StreamManager.get_resumable_stream_id("someone-else", CONV) is None

    async def test_the_index_expires_on_its_own_ttl(self, fake_redis):
        """Sanity: the index is TTL-bound, not permanent. A turn whose process
        died must not leave the conversation permanently 'busy'."""
        await StreamManager.start_stream(SID, CONV, USER)
        assert 0 < await fake_redis.ttl(ACTIVE_KEY) <= STREAM_TTL

        await fake_redis.delete(ACTIVE_KEY)

        assert await StreamManager.get_resumable_stream_id(USER, CONV) is None
