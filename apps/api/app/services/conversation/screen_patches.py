"""The patches that carry a client's screen from one projection of the log to the next.

Each logged entry re-projects the whole log with project_screen and diffs the result: one
projection serves loads and live streams, so no incremental second copy of its rules can drift.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.conversation_frame_models import EntryFrame, EntryUpdatedFrame, WorkDeltaFrame
from app.models.conversation_log_models import LoggedEntry, WorkStarted
from app.models.conversation_screen_models import (
    ScreenInsertFrame,
    ScreenItem,
    ScreenPatch,
    ScreenUpdateFrame,
)
from app.services.conversation.screen import project_screen, work_root


class ScreenItemMoved(Exception):
    """A new projection moved or dropped an item already shown, which the screen's rules forbid."""


def screen_patches(shown: Sequence[ScreenItem], screen: Sequence[ScreenItem]) -> list[ScreenPatch]:
    """Return the inserts and updates that turn shown into screen, applied in order.

    Raises ScreenItemMoved when screen does not keep every shown item in its order.
    """
    before = {item.id: item for item in shown}
    kept = [item.id for item in screen if item.id in before]
    if kept != [item.id for item in shown]:
        raise ScreenItemMoved(f"shown {[item.id for item in shown]}, projected {kept}")
    patches: list[ScreenPatch] = []
    for item in screen:
        old = before.get(item.id)
        if old is None:
            patches.append(ScreenInsertFrame(item=item))
        elif old != item:
            patches.append(ScreenUpdateFrame(item=item))
    return patches


class ScreenTracker:
    """A conversation's log as one reader has it, and the screen it projects to."""

    def __init__(self, entries: Sequence[LoggedEntry]) -> None:
        self._entries = {logged.seq: logged for logged in entries}
        self._started = {
            logged.entry.task_id: logged.entry
            for logged in entries
            if isinstance(logged.entry, WorkStarted)
        }
        self.items = project_screen(entries)

    def on_its_item(self, delta: WorkDeltaFrame) -> WorkDeltaFrame:
        """Return delta addressed to the work item it streams into: the task's, or the one it was handed to."""
        root = work_root(self._started, delta.task_id)
        return delta if root == delta.task_id else delta.model_copy(update={"task_id": root})

    def take(self, frame: EntryFrame | EntryUpdatedFrame) -> list[ScreenPatch]:
        """Take a logged or amended entry and return the patches it makes to the screen."""
        at = frame.at if isinstance(frame, EntryFrame) else self._entries[frame.seq].at
        self._entries[frame.seq] = LoggedEntry(seq=frame.seq, at=at, entry=frame.entry)
        if isinstance(frame.entry, WorkStarted):
            self._started[frame.entry.task_id] = frame.entry
        screen = project_screen([self._entries[seq] for seq in sorted(self._entries)])
        patches = screen_patches(self.items, screen)
        self.items = screen
        return patches
