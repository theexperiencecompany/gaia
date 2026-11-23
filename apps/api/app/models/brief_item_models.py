"""How a brief item stands, and the group it reads in: the one vocabulary every brief surface shares."""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from app.constants.briefing import BriefOutcome


class GroupState(StrEnum):
    """What every item of a composed group is: waiting on the user, done, or still running."""

    NEEDS_YOU = "needs_you"
    DONE = "done"
    IN_PROGRESS = "in_progress"

    @property
    def fallback_heading(self) -> str:
        """Return the heading a group takes when the model's is untrue of its items."""
        return _FALLBACK_HEADINGS[self]


class ItemState(StrEnum):
    """How an item stands: a GAIA action, a user ask, a look-back, work that failed, a plain note.

    An item's text is only its title, so no renderer repeats its state.
    """

    GAIA = "gaia"
    YOU = "you"
    LOOKBACK = "lookback"
    FAILED = "failed"
    NOTE = "note"

    @property
    def label(self) -> str:
        """Return how the state reads where plain text is all there is."""
        return _LABELS[self]

    @property
    def group(self) -> GroupState | None:
        """Return the group the state reads in; None for a note, which no group holds."""
        return _GROUPS[self]

    @property
    def needs_you(self) -> bool:
        """Whether the item waits on the reader: their own asks and work that failed."""
        return self.group is GroupState.NEEDS_YOU

    @property
    def unsaid_outcome(self) -> BriefOutcome:
        """Return the outcome an item gets when its producer named none."""
        return _UNSAID_OUTCOMES[self]


_FALLBACK_HEADINGS: Mapping[GroupState, str] = MappingProxyType(
    {
        GroupState.NEEDS_YOU: "Needs you",
        GroupState.DONE: "Done",
        GroupState.IN_PROGRESS: "Still in progress",
    }
)
_LABELS: Mapping[ItemState, str] = MappingProxyType(
    {
        ItemState.YOU: "Waiting on you",
        ItemState.GAIA: "In progress",
        ItemState.LOOKBACK: "Done",
        ItemState.FAILED: "Failed",
        ItemState.NOTE: "Note",
    }
)
_GROUPS: Mapping[ItemState, GroupState | None] = MappingProxyType(
    {
        ItemState.YOU: GroupState.NEEDS_YOU,
        ItemState.FAILED: GroupState.NEEDS_YOU,
        ItemState.LOOKBACK: GroupState.DONE,
        ItemState.GAIA: GroupState.IN_PROGRESS,
        ItemState.NOTE: None,
    }
)
# Done work finished, GAIA's open work started, the rest changed.
_UNSAID_OUTCOMES: Mapping[ItemState, BriefOutcome] = MappingProxyType(
    {
        ItemState.LOOKBACK: BriefOutcome.FINISHED,
        ItemState.GAIA: BriefOutcome.STARTED,
        ItemState.NOTE: BriefOutcome.CHANGED,
        ItemState.YOU: BriefOutcome.CHANGED,
        ItemState.FAILED: BriefOutcome.CHANGED,
    }
)
