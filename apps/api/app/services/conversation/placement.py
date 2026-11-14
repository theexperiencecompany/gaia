"""Which inputs each reply segment of a comms attempt answers, derived from log order alone.

A segment answers only the inputs logged below the seq its reply opened at; an input handed
to the run after that is answered by the next segment, which opens below it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from app.models.conversation_log_models import LoggedEntry


class PlacementError(Exception):
    """A fact that would put a reply above an input it answers or move a segment already placed."""


@dataclass(frozen=True)
class Segment:
    """One reply segment: the inputs it answers and the seq its reply opened at, None until it opens."""

    covers: tuple[LoggedEntry, ...]
    slot: int | None


def segments(handed: Sequence[LoggedEntry], slots: Sequence[int]) -> tuple[Segment, ...]:
    """Split the inputs handed to a run among the segments that opened at slots, then one unopened tail."""
    _ascending("handed input", [logged.seq for logged in handed])
    _ascending("slot", slots)
    placed: list[Segment] = []
    rest = tuple(handed)
    for slot in slots:
        below = tuple(logged for logged in rest if logged.seq < slot)
        if not below:
            raise PlacementError(f"the segment opened at seq {slot} answers no input below it")
        placed.append(Segment(covers=below, slot=slot))
        rest = rest[len(below) :]
    if rest or not placed:
        placed.append(Segment(covers=rest, slot=None))
    return tuple(placed)


def hand(
    handed: Sequence[LoggedEntry], slots: Sequence[int], settled: int, more: Sequence[LoggedEntry]
) -> tuple[LoggedEntry, ...]:
    """Return handed with more after it; refused when that changes what a settled segment answered."""
    joined = (*handed, *more)
    if segments(joined, slots)[:settled] != segments(handed, slots)[:settled]:
        raise PlacementError(
            f"inputs {[logged.seq for logged in more]} fall into a segment already settled"
        )
    return joined


def open_slot(slots: Sequence[int], segment: int, seq: int) -> tuple[int, ...]:
    """Return slots with segment opened at seq; refused when the segment already sits somewhere."""
    if len(slots) != segment:
        raise PlacementError(f"segment {segment} already opened; it cannot move to seq {seq}")
    return (*slots, seq)


def _ascending(what: str, seqs: Sequence[int]) -> None:
    if any(a >= b for a, b in pairwise(seqs)):
        raise PlacementError(f"{what} seqs {list(seqs)} are not ascending")
