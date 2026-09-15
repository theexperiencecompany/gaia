"""The one integration search every agent tier runs.

The comms discovery tool and the workflow assistant's tools ask the same two
questions ("which of the user's integrations match X?" and "what could they add
from the marketplace?"); answering them here keeps the matching, the
connected-first ordering and the owned-integration exclusion from drifting
between tiers.
"""

from app.helpers.integration_helpers import build_search_matcher
from app.schemas.integrations.responses import CommunityIntegrationItem, MyIntegrationItem
from app.services.integrations.community_service import list_community_integrations
from app.services.integrations.my_integrations import get_my_integrations


async def match_my_integrations(user_id: str, query: str | None) -> list[MyIntegrationItem]:
    """The user's available integrations (platform and their own custom ones)
    matching ``query``, connected ones first. No query means all of them."""
    mine = (await get_my_integrations(user_id)).integrations
    matches = build_search_matcher(query)
    matched = [
        item
        for item in mine
        if item.available
        and matches(f"{item.id} {item.name} {item.category} {item.description}".lower())
    ]
    # Connected first: if a cap ever bites, what gets dropped is an integration
    # the user has not set up, never one they can already use.
    matched.sort(key=lambda item: item.status != "connected")
    return matched


async def match_public_integrations(
    query: str, *, exclude_ids: set[str], limit: int
) -> list[CommunityIntegrationItem]:
    """Marketplace integrations matching ``query`` that are not in ``exclude_ids``,
    at most ``limit``. Over-fetches by the excluded count so an excluded entry
    ranking above the limit cannot crowd out a valid one."""
    excluded = {integration_id.lower() for integration_id in exclude_ids}
    community = await list_community_integrations(search=query, limit=limit + len(excluded))
    return [item for item in community.integrations if item.integration_id.lower() not in excluded][
        :limit
    ]
