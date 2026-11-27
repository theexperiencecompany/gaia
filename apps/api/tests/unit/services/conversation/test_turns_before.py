"""turns_before: what the user said and had been shown when they spoke, read off the log."""

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock

from app.constants.conversation import RECENT_TURNS_LOOKBACK_SEQS
from app.models.conversation_log_models import Entry, Reply
from app.models.message_models import MessageDict
from app.services.conversation.turns_before import turns_before
from tests.unit.services.conversation.log_helpers import logged, settled, user
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, USER


def _reply(text: str, *, heard_through: int | None = None) -> Reply:
    return Reply(
        id="r1",
        reply_id="r1",
        attempt_id="a1",
        text=text,
        heard_through=heard_through,
    )


def _log_of(entries: Sequence[Entry]) -> MagicMock:
    log = MagicMock()
    log.read_after = AsyncMock(
        return_value=[logged(number, entry) for number, entry in enumerate(entries, start=1)]
    )
    return log


async def _turns_before(entries: Sequence[Entry], seq: int) -> list[MessageDict]:
    return await turns_before(_log_of(entries), CONVERSATION, USER, seq)


async def test_the_user_and_the_settled_reply_before_the_point_are_read_in_order() -> None:
    entries: list[Entry] = [user("u0"), _reply("Drafted the reply."), settled("s1", ["u0"], 1)]

    turns = await _turns_before([*entries, user("u1")], seq=4)

    assert turns == [
        {"role": "user", "content": "text of u0"},
        {"role": "assistant", "content": "Drafted the reply."},
    ]


async def test_a_reply_still_being_written_when_the_user_spoke_is_left_out() -> None:
    """Its text grew after their message, so nothing in it was something they had seen."""
    entries: list[Entry] = [
        user("u0"),
        _reply("Drafted the reply to Bob. Also drafted one for Simonne."),
        user("u1"),
        settled("s1", ["u0"], 1),
    ]

    turns = await _turns_before(entries, seq=3)

    assert turns == [{"role": "user", "content": "text of u0"}]


async def test_a_voice_reply_is_read_only_as_far_as_the_user_heard_it() -> None:
    entries: list[Entry] = [
        user("u0"),
        _reply("Draft ready. Say send to send it.", heard_through=11),
        settled("s1", ["u0"], 1),
    ]

    turns = await _turns_before([*entries, user("u1")], seq=4)

    assert turns[-1] == {"role": "assistant", "content": "Draft ready"}


async def test_the_log_is_read_from_the_lookback_window_before_the_point() -> None:
    """Reads this conversation for this user from RECENT_TURNS_LOOKBACK_SEQS before seq."""
    log = _log_of([])

    await turns_before(log, CONVERSATION, USER, 50)

    log.read_after.assert_awaited_once_with(CONVERSATION, USER, 50 - 1 - RECENT_TURNS_LOOKBACK_SEQS)


async def test_a_point_near_the_start_of_the_log_reads_from_the_beginning() -> None:
    log = _log_of([])

    await turns_before(log, CONVERSATION, USER, 5)

    log.read_after.assert_awaited_once_with(CONVERSATION, USER, 0)
