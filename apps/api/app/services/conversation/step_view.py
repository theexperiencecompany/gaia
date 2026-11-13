"""What one comms attempt already knows of its log, so the step re-reads only what moved."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.conversation_log_models import ConversationState, LoggedEntry
from app.services.conversation.ports import Appended


@dataclass
class StepView:
    """The state at one head and every entry after its after seq through that head, as read or written by the step."""

    state: ConversationState
    after: int
    entries: list[LoggedEntry]

    def entries_after(self, since: int, head: int) -> Sequence[LoggedEntry] | None:
        """Return the entries after since when the view holds every one through head; None when the log must be read."""
        if since < self.after or head > self.state.head:
            return None
        return [logged for logged in self.entries if logged.seq > since]

    def state_at(self, head: int) -> ConversationState | None:
        """Return the state when nothing past the view's head was logged; None when the log must be read."""
        return self.state if head <= self.state.head else None

    def appended(self, appended: Appended) -> None:
        """Take in the step's own append; one landing past an entry the view never saw leaves it behind."""
        if appended.duplicate or appended.logged.seq != self.state.head + 1:
            return
        self.entries.append(appended.logged)
        self.state = appended.state

    def amended(self, amended: LoggedEntry) -> None:
        """Take in the step's own amend, which changes an entry's content and never the state."""
        self.entries = [amended if logged.seq == amended.seq else logged for logged in self.entries]

    def phase_set(self, state: ConversationState) -> None:
        """Take in a comms phase the step wrote, when no entry landed since the view's head."""
        if state.head == self.state.head:
            self.state = state
