"""The preempt hint on real Redis and Mongo: raised only forward, dropped when its write fails, rebuilt from the head."""

import pytest

from app.constants.conversation import HINT_KEY_PREFIX, HINT_TTL_SECONDS, HintField
from app.constants.log_tags import LogTag
from app.db.redis import AsyncRedisCommands
from app.db.repositories.conversation_log import ConversationLogRepository
from app.models.conversation_log_models import PreemptHint
from app.services.conversation import mongo_log_hint
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.mongo_log_hint import LogHint, hint_key, publish_hint, raise_hint
from app.utils.errors import ConversationNotFoundError
from tests.unit.services.conversation.log_helpers import barge, logged, opened, stop, user
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")

_COMPLETE: dict[str, str] = {HintField.HEAD: "7", HintField.STOP: "3", HintField.EPOCH: "2"}


@pytest.fixture
def hints() -> LogHint:
    return LogHint(ConversationLogRepository(), FakeClock())


def test_the_hint_key_is_the_users_conversation_under_the_hint_prefix() -> None:
    assert hint_key("c-1", "u-1") == f"{HINT_KEY_PREFIX}u-1:c-1"


async def test_a_complete_hint_is_read_from_redis_without_the_head(
    hints: LogHint, conversation: str, redis: AsyncRedisCommands
) -> None:
    await redis.hset(hint_key(conversation, UID), mapping=_COMPLETE)

    assert await hints.hint(conversation, UID) == PreemptHint(head=7, stop_through=3, epoch=2)


@pytest.mark.parametrize("missing", [HintField.HEAD, HintField.STOP, HintField.EPOCH])
async def test_a_hint_missing_any_required_field_is_rebuilt_from_the_head(
    hints: LogHint,
    log: MongoConversationLog,
    conversation: str,
    redis: AsyncRedisCommands,
    missing: HintField,
) -> None:
    await log.append(conversation, UID, user("m1"))
    claim = await log.claim(conversation, UID)
    assert claim is not None
    await log.append(conversation, UID, user("m2"))
    stopped = (await log.append(conversation, UID, stop("s1", covers_through=1))).state
    partial = {field: value for field, value in _COMPLETE.items() if field != missing}
    await redis.delete(hint_key(conversation, UID))
    await redis.hset(hint_key(conversation, UID), mapping=partial)

    assert stopped.stopped_through == 1
    assert await hints.hint(conversation, UID) == PreemptHint(head=3, stop_through=1, epoch=1)


@pytest.mark.parametrize(
    ("barge_field", "open_field", "expected"),
    [("r1", "r1", "r1"), ("r1", "r2", None), ("r1", "", None), ("", "", None)],
)
async def test_the_barge_reply_is_named_only_while_that_reply_is_open(
    hints: LogHint,
    conversation: str,
    redis: AsyncRedisCommands,
    barge_field: str,
    open_field: str,
    expected: str | None,
) -> None:
    await redis.hset(
        hint_key(conversation, UID),
        mapping={**_COMPLETE, HintField.BARGE: barge_field, HintField.OPEN: open_field},
    )

    assert (await hints.hint(conversation, UID)).barge_reply_id == expected


async def test_a_hint_read_of_a_conversation_the_user_lacks_is_not_found(hints: LogHint) -> None:
    with pytest.raises(ConversationNotFoundError):
        await hints.hint("c-missing", UID)


async def test_publishing_raises_head_stop_and_open_and_sets_the_ttl(
    log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    await log.append(conversation, UID, user("m1"))
    state = (await log.append(conversation, UID, opened("o1", "r9"))).state
    await redis.delete(hint_key(conversation, UID))

    await publish_hint(conversation, UID, logged(2, opened("o1", "r9")), state)

    assert await redis.hgetall(hint_key(conversation, UID)) == {
        HintField.HEAD: "2",
        HintField.STOP: str(state.stopped_through),
        HintField.OPEN: "r9",
    }
    assert HINT_TTL_SECONDS - 5 < await redis.ttl(hint_key(conversation, UID)) <= HINT_TTL_SECONDS


async def test_publishing_with_no_open_reply_writes_an_empty_open(
    log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    state = (await log.append(conversation, UID, user("m1"))).state
    await redis.delete(hint_key(conversation, UID))

    await publish_hint(conversation, UID, logged(1, user("m1")), state)

    assert (await redis.hgetall(hint_key(conversation, UID)))[HintField.OPEN] == ""


async def test_publishing_a_barge_in_names_the_reply_it_barges(
    log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    state = (await log.append(conversation, UID, user("m1"))).state

    await publish_hint(conversation, UID, logged(5, barge("b1", "r4")), state)

    assert (await redis.hgetall(hint_key(conversation, UID)))[HintField.BARGE] == "r4"


class RecordedErrors:
    """Stands in for the wide-event logger, keeping each error line and its fields."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, dict[str, object]]] = []

    def error(self, message: str, **fields: object) -> None:
        self.lines.append((message, fields))


async def test_a_hint_whose_write_fails_is_dropped_for_readers_to_rebuild_and_logged(
    log: MongoConversationLog,
    conversation: str,
    redis: AsyncRedisCommands,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = (await log.append(conversation, UID, user("m1"))).state
    # A string where the hash belongs makes the script's HGET fail with WRONGTYPE.
    await redis.set(hint_key(conversation, UID), "not a hash")
    errors = RecordedErrors()
    monkeypatch.setattr(mongo_log_hint, "log", errors)

    await publish_hint(conversation, UID, logged(2, user("m2")), state)

    assert not await redis.exists(hint_key(conversation, UID))
    [(message, fields)] = errors.lines
    assert message == f"{LogTag.STORAGE} Could not raise a conversation's preempt hint; dropping it"
    assert fields.pop("error_type") == "ResponseError"
    assert "WRONGTYPE" in str(fields.pop("error"))
    assert fields == {"conversation_id": conversation, "seq": 2}


@pytest.mark.parametrize(("value", "raised"), [(4, False), (5, False), (6, True)])
async def test_the_hint_is_raised_only_past_the_value_it_holds(
    conversation: str, redis: AsyncRedisCommands, value: int, raised: bool
) -> None:
    key = hint_key(conversation, UID)
    await redis.hset(key, mapping={HintField.HEAD: "5", HintField.STOP: "1"})

    await raise_hint(conversation, UID, HintField.HEAD, value, {HintField.STOP: 9})

    expected = (
        {HintField.HEAD: str(value), HintField.STOP: "9"}
        if raised
        else {
            HintField.HEAD: "5",
            HintField.STOP: "1",
        }
    )
    assert await redis.hgetall(key) == expected
    assert (await redis.ttl(key) > 0) is raised


async def test_raising_one_guard_leaves_the_others_it_was_not_given(
    conversation: str, redis: AsyncRedisCommands
) -> None:
    key = hint_key(conversation, UID)
    await redis.hset(key, mapping={HintField.HEAD: "5"})

    await raise_hint(conversation, UID, HintField.EPOCH, 3, {})

    assert await redis.hgetall(key) == {HintField.HEAD: "5", HintField.EPOCH: "3"}
