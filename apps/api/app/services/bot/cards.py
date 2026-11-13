"""The tool_data cards a messaging-platform bot receives.

Bots render the same cards the web renders (built per platform in
libs/shared/ts/src/bots/cards), so the API forwards the entries themselves
instead of bot-specific text. What a bot cannot do itself is filled in here as a
card leaves: a rate-limit card gets upgrade_url (null for Pro); a connect card
without a connect_url gets a fresh single-use connect link; approvals and email
drafts get button ids (card_buttons). A background run leaves connect_url unset
on purpose: the link is minted when its result is sent, since the result is read
later than the link would live.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.constants.auth import CONNECT_LINK_TTL_MINUTES
from app.constants.chat import (
    EMAIL_COMPOSE_TOOL_NAME,
    INTEGRATION_CONNECTION_TOOL_NAME,
    RATE_LIMIT_TOOL_NAME,
)
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.models.chat_models import ToolDataEntry, tool_fields
from app.models.payment_models import PlanType
from app.services.bot.card_action_store import new_card_id, store_card
from app.services.bot.card_buttons import (
    ButtonScope,
    approval_buttons,
    carries_buttons,
    email_draft_buttons,
)
from app.services.bot.upgrade_link import UpgradeUrlResolver, bot_upgrade_url_once
from app.services.connect_link_service import build_connect_link_url, integrations_page_url
from shared.py.wide_events import log

#: Cards a bot can render. Loading rows (tool_calls_data, subagent_group) are
#: web-only progress UI and never leave the API.
BOT_CARD_TOOLS: frozenset[str] = frozenset(
    {*tool_fields, APPROVAL_REQUEST_TOOL_NAME, RATE_LIMIT_TOOL_NAME}
)

_TOOL_DATA_ENTRY = TypeAdapter(ToolDataEntry)


class _RateLimitCard(BaseModel):
    current_plan: str | None = None


class _ReconnectAccount(BaseModel):
    id: str | None = None


class _ConnectCard(BaseModel):
    integration_id: str | None = None
    connect_url: str | None = None
    reconnect_account: _ReconnectAccount | None = None


@dataclass(frozen=True)
class BotCardContext:
    """Who one request's cards are for and where they are shown; links are minted only when needed."""

    user_id: str
    #: The conversation the cards are shown in; a tap on one is recorded there.
    conversation_id: str | None
    upgrade_url: UpgradeUrlResolver

    @classmethod
    def for_user(cls, user_id: str, conversation_id: str | None) -> "BotCardContext":
        """Build the context for user_id; the upgrade link is minted at most once."""
        return cls(
            user_id=user_id,
            conversation_id=conversation_id,
            upgrade_url=bot_upgrade_url_once(user_id),
        )


def bot_card_entries(tool_data: object) -> list[ToolDataEntry]:
    """Return the entries of a tool_data payload (one entry or a list) that a bot renders."""
    if tool_data is None:
        return []
    raw_entries = tool_data if isinstance(tool_data, list) else [tool_data]
    entries: list[ToolDataEntry] = []
    for raw in raw_entries:
        try:
            entry: ToolDataEntry = _TOOL_DATA_ENTRY.validate_python(raw)
        except ValidationError as exc:
            log.warning(
                f"{LogTag.API} Bot cards: dropped a malformed tool_data entry",
                error_type=type(exc).__name__,
            )
            continue
        if entry["tool_name"] in BOT_CARD_TOOLS:
            entries.append(entry)
    return entries


async def resolve_bot_cards(tool_data: object, ctx: BotCardContext) -> list[ToolDataEntry]:
    """Return tool_data's bot-renderable entries with links and button ids filled in."""
    return [await _resolve(entry, ctx) for entry in bot_card_entries(tool_data)]


async def _resolve(entry: ToolDataEntry, ctx: BotCardContext) -> ToolDataEntry:
    tool_name = entry["tool_name"]
    if (link := _LINK_ENRICHERS.get(tool_name)) is not None:
        return {**entry, "data": await link(entry["data"], ctx)}
    if (buttons := _BUTTON_ENRICHERS.get(tool_name)) is None:
        return entry
    scope = ButtonScope(
        user_id=ctx.user_id, conversation_id=ctx.conversation_id, card_id=new_card_id()
    )
    resolved: ToolDataEntry = {**entry, "data": await buttons(entry["data"], scope)}
    if carries_buttons(resolved["data"]):
        await store_card(scope.card_id, resolved)
    return resolved


async def _rate_limit(data: object, ctx: BotCardContext) -> object:
    if not isinstance(data, dict):
        return data
    is_pro = _RateLimitCard.model_validate(data).current_plan == PlanType.PRO.value
    return {**data, "upgrade_url": None if is_pro else await ctx.upgrade_url()}


async def _connect(data: object, ctx: BotCardContext) -> object:
    if not isinstance(data, dict):
        return data
    card = _ConnectCard.model_validate(data)
    if card.connect_url or card.integration_id is None:
        return data
    account = card.reconnect_account
    url = await build_connect_link_url(
        ctx.user_id, card.integration_id, account.id if account is not None else None
    )
    if url is None:
        return {**data, "connect_url": integrations_page_url(), "connect_url_valid_minutes": None}
    return {**data, "connect_url": url, "connect_url_valid_minutes": CONNECT_LINK_TTL_MINUTES}


async def _approval(data: object, scope: ButtonScope) -> object:
    if not isinstance(data, dict):
        return data
    return await approval_buttons(data, scope)


async def _email_drafts(data: object, scope: ButtonScope) -> object:
    if not isinstance(data, list):
        return data
    return await email_draft_buttons(data, scope)


_LINK_ENRICHERS: dict[str, Callable[[object, BotCardContext], Awaitable[object]]] = {
    RATE_LIMIT_TOOL_NAME: _rate_limit,
    INTEGRATION_CONNECTION_TOOL_NAME: _connect,
}

_BUTTON_ENRICHERS: dict[str, Callable[[object, ButtonScope], Awaitable[object]]] = {
    APPROVAL_REQUEST_TOOL_NAME: _approval,
    EMAIL_COMPOSE_TOOL_NAME: _email_drafts,
}
