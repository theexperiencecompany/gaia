"""The head read every part of the Mongo conversation log starts from, on real Mongo."""

import pytest

from app.db.repositories.conversation_log import ConversationLogRepository
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.mongo_log_base import MongoLogBase, not_found
from app.utils.errors import ConversationNotFoundError
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import notice
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


@pytest.fixture
def base() -> MongoLogBase:
    return MongoLogBase(ConversationLogRepository(), FakeClock())


async def test_the_head_names_the_seq_of_the_flushed_entry_it_was_asked_about(
    base: MongoLogBase, log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await log.append(conversation, UID, notice("m1"))
    await log.append(conversation, UID, notice("m2"))
    await held.run_all()

    head = await base._head(conversation, UID, "m2")

    assert head.conversation_id == conversation
    assert head.user_id == UID
    assert head.log_head == 2
    assert dict(head.known) == {"m2": 2}


async def test_the_head_asked_about_no_entry_names_no_flushed_one(
    base: MongoLogBase, log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await log.append(conversation, UID, notice("m1"))
    await held.run_all()

    assert dict((await base._head(conversation, UID)).known) == {}


@pytest.mark.parametrize("owner", ["someone_else", UID])
async def test_a_head_the_user_does_not_own_is_not_found(
    base: MongoLogBase, conversation: str, owner: str
) -> None:
    missing = conversation if owner != UID else "c-missing"

    with pytest.raises(ConversationNotFoundError) as raised:
        await base._head(missing, owner)

    assert raised.value.meta == {"conversation_id": missing}
    assert missing in raised.value.message


def test_not_found_names_the_conversation() -> None:
    error = not_found("c-7")

    assert isinstance(error, ConversationNotFoundError)
    assert error.message == "conversation c-7 does not exist for this user"
    assert error.meta == {"conversation_id": "c-7"}
