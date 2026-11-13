"""Bot report of the cards it showed a user, recorded into that conversation."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.constants.chat import ConversationSource
from app.models.chat_models import ToolDataEntry

#: A card's fallback text is a few lines; anything larger is not a card.
BOT_CARD_TEXT_MAX_CHARS = 4000
#: One turn or one proactive message carries a handful of cards at most.
BOT_CARDS_PER_REPORT_MAX = 20


class ReportedBotCard(BaseModel):
    """One card a bot tried to show: what it said, and whether the platform took it."""

    tool_name: str = Field(min_length=1, max_length=64)
    text: str = Field(
        min_length=1,
        max_length=BOT_CARD_TEXT_MAX_CHARS,
        description="The card's text rendering, exactly what a text-only platform would show.",
    )
    delivered: bool


class BotCardsReport(BaseModel):
    """The cards a bot showed (or failed to show) in one conversation."""

    platform: ConversationSource
    platform_user_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    cards: list[ReportedBotCard] = Field(min_length=1, max_length=BOT_CARDS_PER_REPORT_MAX)


class BotCardsRecorded(BaseModel):
    """How many reported cards were written into the conversation record."""

    recorded: int


#: A bot's card builder registry is a dozen tools, not hundreds.
BOT_CARD_TOOLS_MAX = 100


class BotCardActionRequest(BaseModel):
    """A user tapped a button on a bot card; the button carried action_id."""

    platform: ConversationSource
    platform_user_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1, max_length=64)


class BotCardCapabilities(BaseModel):
    """The card tools a bot renders natively, registered when it starts."""

    platform: ConversationSource
    card_tools: list[str] = Field(max_length=BOT_CARD_TOOLS_MAX)


class BotCardCapabilitiesRegistered(BaseModel):
    """How many card tools the platform now has registered."""

    registered: int


class BotCardActionOutcome(StrEnum):
    """How a tap ended, so the bot can tell the user and update the card."""

    DONE = "done"
    ALREADY_DONE = "already_done"
    EXPIRED = "expired"
    FAILED = "failed"


class BotCardActionResult(BaseModel):
    """What the bot shows after a tap: the outcome, a short user-facing line, and the card to redraw."""

    outcome: BotCardActionOutcome
    message: str
    #: The tapped card as it now stands, for the bot to redraw in place; None
    #: when nothing on it changed (an expired or failed tap).
    card: ToolDataEntry | None = None
