"""A card as it stands after one of its buttons was tapped.

The tapped object loses its buttons (so a redraw cannot offer the spent tap
again), keeps the tapped id under bot_tapped (so a bot whose entry renders as
several cards can tell which one was tapped), and, when the tap did its work,
shows the result: the approval decided, the draft sent. Every
other object on the card is untouched, so its buttons stay live.
"""

from collections.abc import Mapping

from app.models.chat_models import ToolDataEntry
from app.schemas.bot_cards import BotCardActionOutcome
from app.services.bot.card_action_store import CardActionKind
from app.services.bot.card_buttons import BOT_ACTIONS_KEY, BOT_TAPPED_KEY

#: What a landed tap changes on the object it was tapped on.
_DONE_STATE: Mapping[CardActionKind, Mapping[str, object]] = {
    CardActionKind.APPROVE: {"status": "approved"},
    CardActionKind.DENY: {"status": "denied"},
    CardActionKind.SEND_EMAIL: {"sent": True},
}


def settle_card(
    card: ToolDataEntry,
    action_id: str,
    kind: CardActionKind,
    outcome: BotCardActionOutcome,
) -> ToolDataEntry:
    """Return card with the object holding action_id settled for the tap's outcome."""
    state = _DONE_STATE[kind] if outcome is BotCardActionOutcome.DONE else {}
    return {**card, "data": _settle(card["data"], action_id, state)}


def _settle(value: object, action_id: str, state: Mapping[str, object]) -> object:
    if isinstance(value, list):
        return [_settle(item, action_id, state) for item in value]
    if not isinstance(value, dict):
        return value
    actions = value.get(BOT_ACTIONS_KEY)
    if isinstance(actions, dict) and action_id in actions.values():
        settled = {key: item for key, item in value.items() if key != BOT_ACTIONS_KEY}
        return {**settled, **state, BOT_TAPPED_KEY: action_id}
    return {key: _settle(item, action_id, state) for key, item in value.items()}
