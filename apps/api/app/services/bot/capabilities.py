"""Which cards each bot platform renders natively, as its bot registered them.

Each bot registers the card tools it has builders for when it starts, so the
API can tell the model, before it replies on that platform, which items the
user already sees as a card rather than in its words.
"""

from app.constants.cache import BOT_CARD_TOOLS_PREFIX
from app.constants.chat import ConversationSource
from app.db.redis import redis_cache


def _key(platform: ConversationSource) -> str:
    return f"{BOT_CARD_TOOLS_PREFIX}{platform.value}"


async def register_card_tools(platform: ConversationSource, card_tools: list[str]) -> int:
    """Replace the platform's registered card tools; returns how many were registered."""
    key = _key(platform)
    async with redis_cache.client.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        if card_tools:
            pipe.sadd(key, *card_tools)
        await pipe.execute()
    return len(set(card_tools))


async def card_tools_for(platform: ConversationSource) -> frozenset[str]:
    """Return the card tools the platform's bot renders; empty until its bot registers."""
    members = await redis_cache.client.smembers(_key(platform))
    return frozenset(str(member) for member in members)
