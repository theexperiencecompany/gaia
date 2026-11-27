"""Reading the conversation log on real Mongo: entries after a seq, the state, and what is still unsettled."""

import pytest

from app.db.repositories.conversation_log import ConversationLogRepository
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.mongo_log_reads import LogReads
from app.utils.errors import ConversationNotFoundError
from tests.unit.services.conversation.log_helpers import notice, replied, user
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


@pytest.fixture
def reads() -> LogReads:
    return LogReads(ConversationLogRepository(), FakeClock())


async def _seed(log: MongoConversationLog, conversation: str) -> None:
    for entry in [user("m1"), *replied("s1", ["m1"], through=1), notice("n1")]:
        await log.append(conversation, UID, entry)


@pytest.mark.parametrize(
    ("after", "ids"), [(0, ["m1", "s1-open", "s1", "n1"]), (2, ["s1", "n1"]), (4, [])]
)
async def test_the_entries_after_a_seq_are_read_in_order(
    reads: LogReads, log: MongoConversationLog, conversation: str, after: int, ids: list[str]
) -> None:
    await _seed(log, conversation)

    assert [e.entry.id for e in await reads.read_after(conversation, UID, after)] == ids


async def test_the_state_is_the_heads(
    reads: LogReads, log: MongoConversationLog, conversation: str
) -> None:
    await _seed(log, conversation)

    state = await reads.state(conversation, UID)

    assert state == await log.state(conversation, UID)
    assert state.settled_through == 1


async def test_the_unsettled_entries_start_after_what_the_reply_settled(
    reads: LogReads, log: MongoConversationLog, conversation: str
) -> None:
    await _seed(log, conversation)

    unsettled = await reads.unsettled(conversation, UID)

    assert unsettled.state.settled_through == 1
    assert [e.entry.id for e in unsettled.entries] == ["s1-open", "s1", "n1"]


async def test_every_read_of_a_conversation_the_user_lacks_is_not_found(
    reads: LogReads, conversation: str
) -> None:
    with pytest.raises(ConversationNotFoundError, match="c-missing"):
        await reads.read_after("c-missing", UID, 0)
    with pytest.raises(ConversationNotFoundError, match=conversation):
        await reads.state(conversation, "someone_else")
    with pytest.raises(ConversationNotFoundError, match="c-missing"):
        await reads.unsettled("c-missing", UID)
    with pytest.raises(ConversationNotFoundError, match="c-missing"):
        await reads.read_screen("c-missing", UID, after=None, limit=1)


async def test_a_screen_window_is_the_repository_s(
    reads: LogReads, log: MongoConversationLog, conversation: str
) -> None:
    await _seed(log, conversation)

    window = await reads.read_screen(conversation, UID, after=2, limit=1)
    assert ([e.entry.id for e in window.entries], window.start) == (
        # The settle's answer is read beside the run.
        ["m1", "s1-open", "s1", "n1"],
        2,
    )
