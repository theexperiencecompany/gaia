"""The ConversationLog contract: a second implementation subclasses ConversationLogContract and provides log_under_test."""

import asyncio

import pytest

from app.models.conversation_log_models import (
    CommsPhase,
    KickStep,
    RejectReason,
    StepClaim,
)
from app.services.conversation.ports import ClaimLost, EntryRejected
from tests.unit.services.conversation.log_helpers import barge, opened, settled, stop, user
from tests.unit.services.conversation.runtime_doubles import FakeClock, LogUnderTest, in_memory_log

CID = "c1"
UID = "user_1"


class ConversationLogContract:
    """Every test here must pass for every ConversationLog implementation."""

    @pytest.fixture
    def subject(self) -> LogUnderTest:
        raise NotImplementedError

    async def _claim(self, subject: LogUnderTest) -> StepClaim:
        claim = await subject.log.claim(CID, UID)
        assert claim is not None
        return claim

    async def test_entries_get_consecutive_seqs_and_read_back_in_order(
        self, subject: LogUnderTest
    ) -> None:
        for entry_id in ("u1", "u2", "u3"):
            await subject.log.append(CID, UID, user(entry_id))
        after = await subject.log.read_after(CID, UID, 1)
        assert [(item.seq, item.entry.id) for item in after] == [(2, "u2"), (3, "u3")]
        assert (await subject.log.state(CID, UID)).unsettled_waking == (1, 2, 3)

    async def test_a_second_append_of_one_id_returns_the_stored_entry_and_changes_nothing(
        self, subject: LogUnderTest
    ) -> None:
        first = await subject.log.append(CID, UID, user("u1"))
        await subject.log.append(CID, UID, user("u2"))
        again = await subject.log.append(CID, UID, user("u1"))
        state = await subject.log.state(CID, UID)
        assert (first.duplicate, again.duplicate) == (False, True)
        assert (again.logged, again.previous, again.state, again.effects) == (
            first.logged,
            state,
            state,
            (),
        )
        assert len(await subject.log.read_after(CID, UID, 0)) == 2

    async def test_a_rejected_entry_raises_and_stores_nothing(self, subject: LogUnderTest) -> None:
        await subject.log.append(CID, UID, user("u1"))
        with pytest.raises(EntryRejected) as rejected:
            await subject.log.append(CID, UID, settled("s", ["u1"], 1, reply_id="nope"))
        assert rejected.value.reason is RejectReason.REPLY_NOT_OPEN
        assert (await subject.log.state(CID, UID)).head == 1
        assert len(await subject.log.read_after(CID, UID, 0)) == 1

    async def test_the_append_reports_the_state_before_and_after_and_its_effects(
        self, subject: LogUnderTest
    ) -> None:
        appended = await subject.log.append(CID, UID, user("u1"))
        assert (appended.previous.head, appended.state.head) == (0, 1)
        assert KickStep() in appended.effects

    async def test_only_one_claim_while_its_holder_is_alive(self, subject: LogUnderTest) -> None:
        first = await self._claim(subject)
        assert await subject.log.claim(CID, UID) is None
        assert await subject.log.beat(first)
        assert await subject.log.claim(CID, UID) is None

    async def test_a_lapsed_holder_is_taken_over_with_a_new_epoch_and_its_writes_fail(
        self, subject: LogUnderTest
    ) -> None:
        old = await self._claim(subject)
        await subject.lapse()
        new = await self._claim(subject)
        assert new.epoch > old.epoch
        assert not await subject.log.beat(old)
        assert (await subject.log.hint(CID, UID)).epoch == new.epoch
        with pytest.raises(ClaimLost):
            await subject.log.append_fenced(old, opened("o"))
        with pytest.raises(ClaimLost):
            await subject.log.set_comms(old, CommsPhase.THINKING)
        with pytest.raises(ClaimLost):
            await subject.log.release_if_caught_up(old)
        assert await subject.log.read_after(CID, UID, 0) == []

    async def test_a_fenced_append_and_the_comms_phase_land_for_the_holder(
        self, subject: LogUnderTest
    ) -> None:
        await subject.log.append(CID, UID, user("u1"))
        claim = await self._claim(subject)
        thinking = await subject.log.set_comms(claim, CommsPhase.THINKING)
        appended = await subject.log.append_fenced(claim, opened("o", "r1"))
        assert thinking.comms is CommsPhase.THINKING
        assert (appended.logged.seq, appended.state.open_reply) == (2, "r1")

    async def test_amend_replaces_content_in_place_without_moving_the_entry(
        self, subject: LogUnderTest
    ) -> None:
        await subject.log.append(CID, UID, user("u1"))
        claim = await self._claim(subject)
        reply = opened("o", "r1")
        await subject.log.append_fenced(claim, reply)
        amended = await subject.log.amend(claim, reply.model_copy(update={"text": "hello"}))
        stored = await subject.log.read_after(CID, UID, 1)
        filled = reply.model_copy(update={"text": "hello", "revision": 1})
        assert (amended.seq, amended.entry, stored[0].entry) == (2, filled, filled)
        assert (await subject.log.state(CID, UID)).head == 2

    async def test_the_hint_names_a_barged_reply_only_while_it_is_open(
        self, subject: LogUnderTest
    ) -> None:
        await subject.log.append(CID, UID, user("u1"))
        claim = await self._claim(subject)
        await subject.log.append_fenced(claim, opened("o", "r1"))
        await subject.log.append(CID, UID, barge("b", "r1"))
        assert (await subject.log.hint(CID, UID)).barge_reply_id == "r1"
        await subject.log.append_fenced(claim, settled("s", ["u1"], 1))
        assert (await subject.log.hint(CID, UID)).barge_reply_id is None

    async def test_the_hint_carries_the_stop_and_the_head(self, subject: LogUnderTest) -> None:
        await subject.log.append(CID, UID, user("u1"))
        await subject.log.append(CID, UID, stop("s"))
        hint = await subject.log.hint(CID, UID)
        assert (hint.head, hint.stop_through) == (2, 1)

    async def test_release_succeeds_only_when_nothing_waking_is_unsettled(
        self, subject: LogUnderTest
    ) -> None:
        claim = await self._claim(subject)
        await subject.log.append(CID, UID, user("u1"))
        assert not await subject.log.release_if_caught_up(claim)
        assert await subject.log.claim(CID, UID) is None
        await subject.log.append(CID, UID, stop("s"))
        assert await subject.log.release_if_caught_up(claim)
        assert await self._claim(subject)

    @pytest.mark.parametrize("append_first", [True, False])
    async def test_an_append_racing_the_release_is_never_lost(
        self, subject: LogUnderTest, append_first: bool
    ) -> None:
        claim = await self._claim(subject)
        release = subject.log.release_if_caught_up(claim)
        append = subject.log.append(CID, UID, user("u1"))
        if append_first:
            appended, released = await asyncio.gather(append, release)
        else:
            released, appended = await asyncio.gather(release, append)
        if released:
            # The holder left, so the append's kick must find the step free to claim.
            assert KickStep() in appended.effects
            assert await subject.log.claim(CID, UID) is not None
        else:
            # The holder stays, and it still sees the input unsettled.
            assert (await subject.log.state(CID, UID)).unsettled_waking == (1,)
            assert await subject.log.claim(CID, UID) is None


class TestInMemoryConversationLog(ConversationLogContract):
    @pytest.fixture
    def subject(self) -> LogUnderTest:
        return in_memory_log(FakeClock(), CID)
