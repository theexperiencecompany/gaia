"""segments, hand and open_slot: which inputs each reply segment answers, from log order alone."""

import pytest

from app.models.conversation_log_models import LoggedEntry
from app.services.conversation.placement import (
    PlacementError,
    Segment,
    hand,
    open_slot,
    segments,
)
from tests.unit.services.conversation.log_helpers import logged, user


def _inputs(*seqs: int) -> tuple[LoggedEntry, ...]:
    return tuple(logged(seq, user(f"u{seq}")) for seq in seqs)


def test_an_unopened_segment_answers_every_handed_input() -> None:
    assert segments(_inputs(1, 2), ()) == (Segment(covers=_inputs(1, 2), slot=None),)


def test_an_input_logged_after_a_slot_goes_to_a_new_segment_below_it() -> None:
    placed = segments(_inputs(1, 2, 5), (4,))
    assert placed == (
        Segment(covers=_inputs(1, 2), slot=4),
        Segment(covers=_inputs(5), slot=None),
    )


def test_an_input_logged_before_the_slot_but_handed_later_joins_that_segment() -> None:
    assert segments(_inputs(1, 3), (4,)) == (Segment(covers=_inputs(1, 3), slot=4),)


def test_each_opened_segment_answers_only_inputs_between_its_slot_and_the_last() -> None:
    placed = segments(_inputs(1, 3, 6), (2, 5, 7))
    assert [segment.covers for segment in placed] == [_inputs(1), _inputs(3), _inputs(6)]


def test_a_segment_that_opened_with_nothing_below_it_is_refused() -> None:
    with pytest.raises(PlacementError, match="answers no input"):
        segments(_inputs(1), (2, 3))


@pytest.mark.parametrize(
    ("handed", "slots", "refusal"),
    [
        ((2, 1), (), "handed input seqs [2, 1] are not ascending"),
        ((1,), (3, 3), "slot seqs [3, 3] are not ascending"),
    ],
)
def test_seqs_out_of_log_order_are_refused(
    handed: tuple[int, ...], slots: tuple[int, ...], refusal: str
) -> None:
    with pytest.raises(PlacementError) as refused:
        segments(_inputs(*handed), slots)
    assert str(refused.value) == refusal


def test_handing_an_input_into_a_settled_segment_is_refused() -> None:
    # Segment 0 settled answering u1 at slot 4; u3, logged below that slot, would change its answers.
    with pytest.raises(PlacementError, match="already settled"):
        hand(_inputs(1), (4,), 1, _inputs(3))


def test_handing_an_input_after_every_settled_slot_extends_the_open_segment() -> None:
    assert hand(_inputs(1, 5), (4,), 1, _inputs(6)) == _inputs(1, 5, 6)


def test_a_segment_opens_once_and_never_moves() -> None:
    assert open_slot((4,), 1, 7) == (4, 7)
    with pytest.raises(PlacementError, match="cannot move"):
        open_slot((4,), 0, 7)
