"""The brief's skim text: the one short shape every surface leads with.

Headline, at most MAX_SKIM_ASKS things waiting on the user, one sentence on what
happened overnight, then the link. Chat caption and email subject/preheader are cut from it.
"""

from dataclasses import dataclass

from app.config.settings import settings
from app.models.briefing_models import BriefingItem, BriefingPayload

MAX_SKIM_ASKS = 3
_ASK_KINDS = frozenset({"you"})
_RETRY_PREFIX = "Retry: "
_OVERNIGHT_NAMED = 2
_PARAGRAPH = "\n\n"
_DAY_PERIOD = "Overnight"
_WEEK_PERIOD = "This week"


@dataclass(frozen=True)
class Skim:
    headline: str
    asks: list[str]
    overnight: str | None

    def text(self, link: str) -> str:
        """Return the full skim, paragraph per block, ending on link, as the chat caption."""
        blocks = [self.headline]
        if self.asks:
            blocks.append("\n".join(f"• {ask}" for ask in self.asks))
        if self.overnight:
            blocks.append(self.overnight)
        blocks.append(f"Full brief: {link}")
        return _PARAGRAPH.join(blocks)

    @property
    def preheader(self) -> str:
        """The email preview line under the subject (the subject is the headline)."""
        return " · ".join([*self.asks, *([self.overnight] if self.overnight else [])])


def _ask(item: BriefingItem) -> str:
    return f"{_RETRY_PREFIX}{item.text}" if item.kind == "failed" else item.text


def _named(titles: list[str]) -> str:
    shown = titles[:_OVERNIGHT_NAMED]
    more = len(titles) - len(shown)
    if more:
        return f"{', '.join(shown)} and {more} more"
    return " and ".join(shown)


def _overnight(done: list[str], running: list[str], period: str) -> str | None:
    """One sentence on GAIA's work over period ("Overnight", "This week")."""
    verb = "is" if len(running) == 1 else "are"
    if done and running:
        return f"{period} I finished {_named(done)}; {_named(running)} {verb} still in progress."
    if done:
        return f"{period} I finished {_named(done)}."
    if running:
        return f"{period} {_named(running)} {verb} in progress."
    return None


def full_brief_url(briefing_id: str) -> str:
    """Where the skim's link sends the reader: the brief's own page in the app."""
    return f"{settings.FRONTEND_URL}{brief_path(briefing_id)}"


def brief_path(briefing_id: str) -> str:
    """Return the app path of one brief's standalone page."""
    return f"/brief/{briefing_id}"


def build_skim(payload: BriefingPayload) -> Skim:
    items = [item for section in payload.sections for item in section.items]
    asks = [_ask(i) for i in items if i.kind in _ASK_KINDS or i.kind == "failed"]
    return Skim(
        headline=payload.headline,
        asks=asks[:MAX_SKIM_ASKS],
        overnight=_overnight(
            [i.text for i in items if i.kind == "lookback"],
            [i.text for i in items if i.kind == "gaia"],
            _WEEK_PERIOD if payload.mood == "weekly" else _DAY_PERIOD,
        ),
    )
