"""What an attempt owes and how far its settles move the settled mark, from log order alone."""

from hypothesis import given, strategies as st

from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import LoggedEntry, Reaction
from app.services.conversation.placement import owed, watermark
from tests.unit.services.conversation.log_helpers import finished, logged, user


def _handed(count: int) -> list[LoggedEntry]:
    return [logged(seq, user(f"u{seq}")) for seq in range(1, count + 1)]


def test_every_user_message_is_owed_but_one_an_instant_reaction_answered_and_other_inputs() -> None:
    acked = user("u2").model_copy(update={"reaction": Reaction(emoji="👀", by=ReactionBy.JEV)})
    by_model = user("u3").model_copy(
        update={"reaction": Reaction(emoji="👍", by=ReactionBy.CHAT_MODEL)}
    )
    entries = [
        logged(1, user("u1")),
        logged(2, acked),
        logged(3, by_model),
        logged(4, finished("f", "t1")),
    ]
    assert owed(entries) == {1: "u1", 3: "u3"}


def test_a_later_message_answered_first_holds_the_mark_below_the_open_one() -> None:
    handed = _handed(3)
    assert watermark(handed, {2, 3}, 0) == 0
    assert watermark(handed, {1, 3}, 0) == 1
    assert watermark(handed, {1, 2, 3}, 0) == 3


@given(st.integers(1, 8), st.sets(st.integers(1, 8)))
def test_the_mark_is_the_newest_seq_below_which_everything_is_answered(
    count: int, answered: set[int]
) -> None:
    handed = _handed(count)
    through = watermark(handed, answered, 0)
    assert all(seq in answered for seq in range(1, through + 1))
    assert through == count or through + 1 not in answered
