"""Bot routes for cards: reporting what a bot showed, a tap on a card button, and
the cards a bot renders.

Mounted on the shared /api/v1/bot prefix; the bot API key is the credential.
"""

from fastapi import APIRouter, HTTPException, Request

from app.api.v1.endpoints.bot import require_bot_api_key
from app.models.user_models import AuthenticatedUser
from app.schemas.bot_cards import (
    BotCardActionRequest,
    BotCardActionResult,
    BotCardCapabilities,
    BotCardCapabilitiesRegistered,
    BotCardsRecorded,
    BotCardsReport,
)
from app.services.bot.capabilities import register_card_tools
from app.services.bot.card_actions import perform_card_action
from app.services.bot.card_record import record_bot_cards
from app.utils.auth_utils import resolve_bot_user
from shared.py.wide_events import log

router = APIRouter()


@router.post(
    "/cards-delivered",
    summary="Report Cards Shown",
    description="Record the cards a bot showed (or failed to show) in a conversation.",
)
async def report_bot_cards(request: Request, body: BotCardsReport) -> BotCardsRecorded:
    """Record each reported card in the conversation the model reads."""
    await require_bot_api_key(request)
    log.set(
        operation="report_bot_cards",
        conversation_id=body.conversation_id,
        bot_cards={"platform": body.platform.value, "count": len(body.cards)},
    )
    user = await _linked_caller(request, body.platform.value, body.platform_user_id)
    recorded = await record_bot_cards(body, user.user_id)
    log.set_ns("bot_cards", recorded=recorded)
    return BotCardsRecorded(recorded=recorded)


@router.post(
    "/card-action",
    summary="Perform Card Action",
    description="Perform the operation a tapped bot card button stands for.",
)
async def perform_bot_card_action(
    request: Request, body: BotCardActionRequest
) -> BotCardActionResult:
    """Run the tapped button's operation for the linked user and record it in the conversation."""
    await require_bot_api_key(request)
    log.set(operation="bot_card_action", bot_card_action={"platform": body.platform.value})
    user = await _linked_caller(request, body.platform.value, body.platform_user_id)
    result = await perform_card_action(body.action_id, user.user_id, body.platform)
    log.set_ns("bot_card_action", outcome=result.outcome.value)
    return result


@router.post(
    "/capabilities",
    summary="Register Card Capabilities",
    description="Register the card tools a bot renders natively on its platform.",
)
async def register_bot_capabilities(
    request: Request, body: BotCardCapabilities
) -> BotCardCapabilitiesRegistered:
    """Replace the platform's registered card tools with the bot's current builders."""
    await require_bot_api_key(request)
    log.set(operation="register_bot_capabilities", bot_cards={"platform": body.platform.value})
    if request.state.bot_platform != body.platform.value:
        raise HTTPException(status_code=403, detail="Body does not match the bot platform header")
    registered = await register_card_tools(body.platform, body.card_tools)
    log.set_ns("bot_cards", registered=registered)
    return BotCardCapabilitiesRegistered(registered=registered)


async def _linked_caller(
    request: Request, platform: str, platform_user_id: str
) -> AuthenticatedUser:
    """The linked user the bot is acting for; refuse a body that disagrees with the headers."""
    if (
        request.state.bot_platform != platform
        or request.state.bot_platform_user_id != platform_user_id
    ):
        raise HTTPException(status_code=403, detail="Body does not match the bot platform headers")
    user = await resolve_bot_user(platform, platform_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Platform account is not linked")
    return user
