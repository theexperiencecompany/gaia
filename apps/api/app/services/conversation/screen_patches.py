"""The patches that carry a client's screen from one projection of the log to the next.

Each logged entry or published work card re-projects the whole log with project_screen, folds
running work's cards onto its item, and diffs the result: one projection serves loads and live
streams, so no incremental second copy of its rules can drift.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    StreamPayload,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import LoggedEntry, WorkStarted
from app.models.conversation_screen_models import (
    ScreenInsertFrame,
    ScreenItem,
    ScreenPatch,
    ScreenUpdateFrame,
    WorkItem,
)
from app.services.conversation.screen import (
    LIVE_WORK,
    Positioned,
    project_screen,
    work_root,
    work_timeline,
)
from app.services.conversation.tool_cards import fold_cards
from app.services.conversation.work_deltas import work_payloads


class ScreenItemMoved(Exception):
    """A new projection moved or dropped an item already shown, which the screen's rules forbid."""


def screen_patches(
    shown: Sequence[ScreenItem], screen: Sequence[ScreenItem], head: int
) -> list[ScreenPatch]:
    """Return the inserts and updates that turn shown into screen, the log at head, applied in order.

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
            patches.append(ScreenInsertFrame(item=item, head=head))
        elif old != item:
            patches.append(ScreenUpdateFrame(item=item, head=head))
    return patches


class ScreenTracker:
    """A conversation's log as one reader has it, and the screen it projects to with its live work's cards."""

    def __init__(
        self,
        conversation_id: str,
        entries: Sequence[Positioned],
        work: Mapping[str, Sequence[StreamPayload]],
    ) -> None:
        self._conversation_id = conversation_id
        self._entries = {
            logged.seq: LoggedEntry(seq=logged.seq, at=logged.at, entry=logged.entry)
            for logged in entries
        }
        self._started = {
            logged.entry.task_id: logged.entry
            for logged in entries
            if isinstance(logged.entry, WorkStarted)
        }
        self._work = {task_id: list(payloads) for task_id, payloads in work.items()}
        self.items = self._project()

    @classmethod
    async def load(cls, conversation_id: str, entries: Sequence[Positioned]) -> ScreenTracker:
        """Return the tracker for entries, holding what each running task's work has published so far."""
        live = {
            item.task_id
            for item in project_screen(entries)
            if isinstance(item, WorkItem) and item.status in LIVE_WORK
        }
        started = {
            logged.entry.task_id: logged.entry
            for logged in entries
            if isinstance(logged.entry, WorkStarted)
        }
        work = {
            task_id: await work_payloads(conversation_id, task_id)
            for task_id in started
            if work_root(started, task_id) in live
        }
        return cls(conversation_id, entries, work)

    @property
    def head(self) -> int:
        """Return the seq of the newest entry held: the log's head the items project."""
        return max(self._entries, default=0)

    def _project(self) -> list[ScreenItem]:
        entries = [self._entries[seq] for seq in sorted(self._entries)]
        return [self._with_live_cards(item) for item in project_screen(entries)]

    def _with_live_cards(self, item: ScreenItem) -> ScreenItem:
        if not isinstance(item, WorkItem) or item.status not in LIVE_WORK:
            return item
        chain = [task for task in self._started if work_root(self._started, task) == item.task_id]
        live = fold_cards(payload for task in chain for payload in self._work.get(task, ()))
        return item.model_copy(
            update={
                "tool_data": live.tool_data,
                "timeline": work_timeline(item.handoff, live.tool_data, item.approvals),
                "image": live.image,
            }
        )

    async def on_work(self, delta: WorkDeltaFrame) -> list[ScreenPatch]:
        """Take one published card of running work and return the update to its item."""
        held = self._work.setdefault(delta.task_id, [])
        if delta.index < len(held):
            return []
        if delta.index == len(held):
            held.append(delta.payload)
        else:
            # A gap: this reader missed frames, so the task's record is the truth.
            self._work[delta.task_id] = await work_payloads(self._conversation_id, delta.task_id)
        root = work_root(self._started, delta.task_id)
        patches: list[ScreenPatch] = []
        for index, item in enumerate(self.items):
            if isinstance(item, WorkItem) and item.task_id == root:
                updated = self._with_live_cards(item)
                if updated != item:
                    self.items[index] = updated
                    patches.append(ScreenUpdateFrame(item=updated, head=self.head))
        return patches

    def take(self, frame: EntryFrame | EntryUpdatedFrame) -> list[ScreenPatch]:
        """Take a logged or amended entry and return the patches it makes to the screen."""
        at = frame.at if isinstance(frame, EntryFrame) else self._entries[frame.seq].at
        self._entries[frame.seq] = LoggedEntry(seq=frame.seq, at=at, entry=frame.entry)
        if isinstance(frame.entry, WorkStarted):
            self._started[frame.entry.task_id] = frame.entry
        return self._repatch()

    def _repatch(self) -> list[ScreenPatch]:
        screen = self._project()
        patches = screen_patches(self.items, screen, self.head)
        self.items = screen
        return patches
