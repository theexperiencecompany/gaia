"""When a streaming reply first showed on the client, net of text the graph retracted.

A reply's saved date is where it sorts, so it must be when the user first saw
the content they keep: a message they send after reading it then never lands
above it. Text is provisional until its message boundary says it was kept; a
discarded boundary (a tool-call preamble, an abandoned model attempt) takes it
off the screen again. A card is never retracted.
"""

from datetime import UTC, datetime


class ReplyVisibility:
    """The stamps of what is on screen: kept content, and the message still streaming."""

    __slots__ = ("_kept_at", "_open_text_at")

    def __init__(self) -> None:
        self._kept_at: datetime | None = None
        self._open_text_at: datetime | None = None

    @property
    def first_shown_at(self) -> datetime | None:
        """When the earliest content still on screen first showed, or None while nothing is."""
        stamps = [stamp for stamp in (self._kept_at, self._open_text_at) if stamp is not None]
        return min(stamps, default=None)

    def saw_text(self) -> None:
        """Stamp the streaming message's first visible text; later text keeps that stamp."""
        if self._open_text_at is None:
            self._open_text_at = datetime.now(UTC)

    def saw_card(self) -> None:
        """Stamp the first card; a card stays on screen whatever its message's fate."""
        if self._kept_at is None:
            self._kept_at = datetime.now(UTC)

    def settle(self, *, discarded: bool) -> None:
        """Close the streaming message: its text stays on screen, or is retracted."""
        if not discarded:
            self._kept_at = self.first_shown_at
        self._open_text_at = None
