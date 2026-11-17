"""What one scenario looked like from the user's Telegram client: what I sent, every bot bubble's text over time, reactions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class TextState:
    """One observed text of a bot message, seconds after the scenario started."""

    at: float
    text: str


@dataclass
class ReactionState:
    """The reactions on one of my messages as observed at a moment."""

    at: float
    emojis: tuple[str, ...]


@dataclass
class SentMessage:
    """A message I sent, with every reaction state the bot put on it."""

    id: int
    text: str
    sent_at: float
    reactions: list[ReactionState] = field(default_factory=list)

    @property
    def first_reaction_at(self) -> float | None:
        """When a reaction first appeared on this message, or None."""
        return next((r.at for r in self.reactions if r.emojis), None)


@dataclass
class BotMessage:
    """A bot bubble: its quote target and the text it showed over time."""

    id: int
    created_at: float
    reply_to: int | None
    states: list[TextState] = field(default_factory=list)
    entity_kinds: list[str] = field(default_factory=list)
    deleted_at: float | None = None

    @property
    def text(self) -> str:
        """The last text this bubble showed."""
        return self.states[-1].text if self.states else ""


@dataclass
class Mark:
    """A runner action worth seeing on the timeline (a restart, a step timeout)."""

    at: float
    kind: str
    detail: str = ""


@dataclass
class Transcript:
    """Everything one scenario run showed the user, in observation order."""

    scenario: str
    sent: list[SentMessage] = field(default_factory=list)
    bot: list[BotMessage] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    ended_at: float = 0.0

    def bot_after(self, at: float) -> list[BotMessage]:
        """Bot bubbles that first appeared after a moment, oldest first."""
        return [m for m in self.bot if m.created_at > at]

    def next_send_after(self, at: float) -> float:
        """When I next sent something after a moment, else the end of the run."""
        return min((s.sent_at for s in self.sent if s.sent_at > at), default=self.ended_at)

    def to_json(self) -> dict[str, object]:
        """Return the transcript as plain JSON."""
        return asdict(self)
