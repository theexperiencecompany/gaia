"""Compute which integrations a workflow's steps require and which are missing."""

from functools import lru_cache

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.workflow_models import IntegrationRef, WorkflowStep


@lru_cache(maxsize=1)
def _category_to_integration() -> dict[str, str]:
    """Map category names to integration IDs using the static OAUTH catalog.

    Covers both registry categories (via subagent_config.tool_space) and
    subagent integration IDs used directly as step categories.
    """
    result: dict[str, str] = {}
    for integration in OAUTH_INTEGRATIONS:
        if integration.subagent_config and integration.subagent_config.tool_space:
            result[integration.subagent_config.tool_space.lower()] = integration.id
        # integration.id itself is also used as a category name in the LLM palette
        result[integration.id.lower()] = integration.id
    return result


@lru_cache(maxsize=1)
def _integration_name_map() -> dict[str, str]:
    return {i.id: i.name for i in OAUTH_INTEGRATIONS}


def compute_required_integrations(steps: list[WorkflowStep]) -> set[str]:
    """Return integration IDs required by the workflow's steps.

    A step requires an integration when its category maps to a provider-specific
    entry in the OAUTH catalog. Core categories (search, todos, gaia, etc.) are
    not in the catalog and are therefore not required.
    """
    cat_map = _category_to_integration()
    required: set[str] = set()
    for step in steps:
        integration_id = cat_map.get(step.category.lower())
        if integration_id:
            required.add(integration_id)
    return required


async def compute_missing_integrations(
    required: set[str],
    user_id: str,
) -> list[IntegrationRef]:
    """Return IntegrationRef objects for required integrations not yet connected."""
    if not required:
        return []
    # Deferred to avoid circular import: oauth_service → provisioner → service → here
    from app.services.oauth.oauth_service import get_all_integrations_status

    name_map = _integration_name_map()
    status_map = await get_all_integrations_status(user_id)
    missing: list[IntegrationRef] = []
    for integration_id in sorted(required):
        if not status_map.get(integration_id, False):
            missing.append(
                IntegrationRef(id=integration_id, name=name_map.get(integration_id, integration_id))
            )
    return missing
