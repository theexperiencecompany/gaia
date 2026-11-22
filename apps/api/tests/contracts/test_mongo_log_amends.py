"""Amending stored entries on real Mongo: the step's fenced fill and the user's one reaction, each at its next revision."""

import pytest

from app.db.redis import AsyncRedisCommands
from app.db.repositories.conversation_log import ConversationLogRepository
from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import (
    Entry,
    LoggedEntry,
    Reaction,
    RejectReason,
    Reply,
    StepClaim,
    UserMessage,
)
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.mongo_log_amends import LogAmends
from app.services.conversation.mongo_log_claim import alive_key
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.utils.errors import ConversationEntryNotFoundError, ConversationNotFoundError
from tests.unit.services.conversation.log_helpers import notice, opened, user
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")

_THUMBS = Reaction(emoji="👍", by=ReactionBy.JEV)


@pytest.fixture
def amends() -> LogAmends:
    return LogAmends(ConversationLogRepository(), FakeClock())


async def _claimed(log: MongoConversationLog, conversation: str) -> StepClaim:
    claim = await log.claim(conversation, UID)
    assert claim is not None
    return claim


async def _stored(log: MongoConversationLog, conversation: str, entry_id: str) -> LoggedEntry:
    return next(e for e in await log.read_after(conversation, UID, 0) if e.entry.id == entry_id)


async def test_a_fill_replaces_the_reply_at_its_next_revision_and_keeps_the_users_pin(
    amends: LogAmends, log: MongoConversationLog, conversation: str
) -> None:
    claim = await _claimed(log, conversation)
    await log.append_fenced(claim, notice("n1"))
    await log.append_fenced(claim, opened("o1"))
    await ConversationLogRepository().set_pinned(
        conversation, user_id=UID, message_id="r1", pinned=True
    )
    pinned = (await _stored(log, conversation, "o1")).entry
    assert isinstance(pinned, Reply)
    assert pinned.pinned
    filled = opened("o1").model_copy(update={"text": "Hello"})

    amended = await amends.amend(claim, filled)

    assert amended.seq == 2
    assert amended.entry == filled.model_copy(
        update={"revision": pinned.revision + 1, "pinned": True}
    )
    assert (await _stored(log, conversation, "o1")).entry == amended.entry


async def test_pinned_reads_only_the_messages_and_replies_the_user_pinned(
    log: MongoConversationLog, conversation: str
) -> None:
    claim = await _claimed(log, conversation)
    await log.append_fenced(claim, opened("o1"))
    await log.append(conversation, UID, user("u1"))
    await log.append(conversation, UID, user("u2"))
    repository = ConversationLogRepository()
    await repository.set_pinned(conversation, user_id=UID, message_id="r1", pinned=True)
    await repository.set_pinned(conversation, user_id=UID, message_id="u2", pinned=True)

    assert [item.entry.id for item in await log.pinned(conversation, UID)] == ["o1", "u2"]


async def test_a_fill_that_takes_back_shown_text_is_refused(
    amends: LogAmends, log: MongoConversationLog, conversation: str
) -> None:
    claim = await _claimed(log, conversation)
    await log.append_fenced(claim, opened("o1"))
    await amends.amend(claim, opened("o1").model_copy(update={"text": "Hello"}))

    with pytest.raises(EntryRejected) as raised:
        await amends.amend(claim, opened("o1").model_copy(update={"text": "Help"}))

    assert raised.value.reason is RejectReason.SHOWN_TEXT_TAKEN_BACK
    kept = (await _stored(log, conversation, "o1")).entry
    assert isinstance(kept, Reply)
    assert kept.text == "Hello"


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param(None, id="no-such-entry"),
        pytest.param(notice("o1"), id="an-entry-of-another-kind"),
        pytest.param(user("o1"), id="a-message-where-a-reply-was-asked-for"),
    ],
)
async def test_a_fill_of_no_stored_reply_with_that_id_is_not_found(
    amends: LogAmends,
    log: MongoConversationLog,
    conversation: str,
    stored: Entry | None,
) -> None:
    claim = await _claimed(log, conversation)
    if stored is not None:
        await log.append_fenced(claim, stored)

    with pytest.raises(ConversationEntryNotFoundError) as raised:
        await amends.amend(claim, opened("o1"))

    assert raised.value.meta == {"conversation_id": conversation, "entry_id": "o1"}
    assert "o1" in raised.value.message
    assert conversation in raised.value.message


async def test_a_fill_in_a_conversation_the_user_lacks_is_not_found(amends: LogAmends) -> None:
    claim = StepClaim(conversation_id="c-missing", user_id=UID, epoch=1, took_over=False)

    with pytest.raises(ConversationNotFoundError) as raised:
        await amends.amend(claim, opened("o1"))

    assert raised.value.meta == {"conversation_id": "c-missing"}


async def test_a_fill_by_a_lost_claim_never_lands(
    amends: LogAmends, log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await _claimed(log, conversation)
    await log.append_fenced(claim, opened("o1"))
    await redis.delete(alive_key(conversation, UID, 1))
    await _claimed(log, conversation)

    with pytest.raises(ClaimLost):
        await amends.amend(claim, opened("o1").model_copy(update={"text": "late"}))

    assert (await _stored(log, conversation, "o1")).entry == opened("o1")


async def test_a_reaction_lands_once_at_the_messages_next_revision(
    amends: LogAmends, log: MongoConversationLog, conversation: str
) -> None:
    await log.append(conversation, UID, notice("n1"))
    await log.append(conversation, UID, user("m1"))

    reacted = await amends.react_once(conversation, UID, "m1", _THUMBS)

    assert reacted is not None
    assert reacted.seq == 2
    assert reacted.entry == user("m1").model_copy(update={"reaction": _THUMBS, "revision": 1})
    assert (await _stored(log, conversation, "m1")).entry == reacted.entry


async def test_a_second_reaction_is_refused_and_leaves_the_first(
    amends: LogAmends, log: MongoConversationLog, conversation: str
) -> None:
    await log.append(conversation, UID, user("m1"))
    await amends.react_once(conversation, UID, "m1", _THUMBS)

    other = Reaction(emoji="🎉", by=ReactionBy.CHAT_MODEL)
    assert await amends.react_once(conversation, UID, "m1", other) is None
    kept = (await _stored(log, conversation, "m1")).entry
    assert isinstance(kept, UserMessage)
    assert kept.reaction == _THUMBS


async def test_a_reaction_to_a_message_that_moved_on_since_the_read_is_dropped(
    log: MongoConversationLog, conversation: str
) -> None:
    await log.append(conversation, UID, user("m1"))

    class MovedOn(ConversationLogRepository):
        async def stage_unfenced_amend(
            self,
            conversation_id: str,
            *,
            user_id: str,
            amended: LoggedEntry,
            after_revision: int,
            advances_sync: bool = False,
        ) -> bool:
            # Another writer bumped the message between the read and this stage.
            return await super().stage_unfenced_amend(
                conversation_id,
                user_id=user_id,
                amended=amended,
                after_revision=after_revision + 1,
                advances_sync=advances_sync,
            )

    assert (
        await LogAmends(MovedOn(), FakeClock()).react_once(conversation, UID, "m1", _THUMBS) is None
    )
    assert (await _stored(log, conversation, "m1")).entry == user("m1")


@pytest.mark.parametrize(
    "conversation_of",
    [pytest.param(True, id="no-such-message"), pytest.param(False, id="no-such-conversation")],
)
async def test_a_reaction_to_no_user_message_is_not_found(
    amends: LogAmends, log: MongoConversationLog, conversation: str, conversation_of: bool
) -> None:
    await log.append(conversation, UID, notice("n1"))
    target = conversation if conversation_of else "c-missing"

    with pytest.raises(ConversationEntryNotFoundError) as raised:
        await amends.react_once(target, UID, "n1", _THUMBS)

    assert raised.value.meta == {"conversation_id": target, "entry_id": "n1"}
    assert "n1" in raised.value.message
    assert target in raised.value.message
