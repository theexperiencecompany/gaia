"""Compute which integrations a workflow requires and which are missing."""

from collections.abc import Sequence
from functools import lru_cache

from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.constants.integrations import MANAGED_BY_INTERNAL
from app.models.workflow_models import (
    IntegrationRef,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
from app.utils.trigger_utils import get_integration_for_trigger


@lru_cache(maxsize=1)
def _category_to_integration() -> dict[str, str]:
    """Map category names to integration IDs using the static OAUTH catalog.

    Covers both registry categories (via subagent_config.tool_space) and
    subagent integration IDs used directly as step categories.

    Internal integrations (todos, reminders, …) are excluded — they are
    always available and never require the user to connect anything.
    """
    result: dict[str, str] = {}
    for integration in OAUTH_INTEGRATIONS:
        if integration.managed_by == MANAGED_BY_INTERNAL:
            continue
        if integration.subagent_config and integration.subagent_config.tool_space:
            result[integration.subagent_config.tool_space.lower()] = integration.id
        # integration.id itself is also used as a category name in the LLM palette
        result[integration.id.lower()] = integration.id
    return result


@lru_cache(maxsize=1)
def _integration_name_map() -> dict[str, str]:
    return {i.id: i.name for i in OAUTH_INTEGRATIONS}


def compute_required_integrations(
    steps: list[WorkflowStep],
    trigger_config: TriggerConfig | None = None,
) -> set[str]:
    """Return integration IDs a workflow requires.

    A step requires an integration when its category maps to a provider-specific
    entry in the OAUTH catalog; an integration-trigger workflow additionally
    requires the integration that owns its trigger. Core categories (search,
    todos, gaia, etc.) are not in the catalog and are therefore not required.
    """
    cat_map = _category_to_integration()
    required: set[str] = set()
    for step in steps:
        integration_id = cat_map.get(step.category.lower())
        if integration_id:
            required.add(integration_id)
    if (
        trigger_config is not None
        and trigger_config.type == TriggerType.INTEGRATION
        and trigger_config.trigger_name
    ):
        trigger_integration = get_integration_for_trigger(trigger_config.trigger_name)
        if trigger_integration:
            required.add(trigger_integration)
    return required


def build_integration_refs(
    required: set[str],
    status_map: dict[str, bool],
) -> tuple[list[IntegrationRef], list[IntegrationRef]]:
    """Split `required` into (all required refs, missing refs) against a connection
    status map. Pure — the caller owns the (cached) status fetch, so a workflow list
    resolves every row from a single `get_all_integrations_status` call."""
    name_map = _integration_name_map()
    required_refs = [
        IntegrationRef(id=iid, name=name_map.get(iid, iid)) for iid in sorted(required)
    ]
    missing_refs = [ref for ref in required_refs if not status_map.get(ref.id, False)]
    return required_refs, missing_refs


async def compute_missing_integrations(
    required: set[str],
    user_id: str,
) -> list[IntegrationRef]:
    """Return IntegrationRef objects for required integrations not yet connected."""
    if not required:
        return []
    # Deferred to avoid circular import: oauth_service → provisioner → service → here
    from app.services.oauth.oauth_service import get_all_integrations_status

    status_map = await get_all_integrations_status(user_id)
    return build_integration_refs(required, status_map)[1]


async def confirm_disconnected(user_id: str, integration_ids: Sequence[str]) -> list[str]:
    """The subset of ``integration_ids`` the user genuinely has not connected.

    Unlike everything else in this module, the ids here do not come from the
    workflow's declared steps — they come from a run reporting what it actually
    found, and a run is a model. It can name an integration that does not exist,
    or one that is connected and failed for some unrelated reason. Either would
    pause a working workflow, so the claim is checked against real connection
    status first: the run proposes, this disposes.

    Unknown ids are dropped rather than reported missing. An id GAIA has no
    integration for cannot be the thing the user needs to go and connect.
    """
    if not integration_ids:
        return []
    # Deferred to avoid circular import: oauth_service → provisioner → service → here
    from app.services.oauth.oauth_service import get_all_integrations_status

    status_map = await get_all_integrations_status(user_id)
    return [
        integration_id
        for integration_id in dict.fromkeys(integration_ids)
        if get_integration_by_id(integration_id) is not None and not status_map.get(integration_id)
    ]


async def compute_integration_refs(
    steps: list[WorkflowStep],
    trigger_config: TriggerConfig | None,
    user_id: str,
) -> tuple[list[IntegrationRef], list[IntegrationRef]]:
    """Resolve (required, missing) refs for one workflow in a single status fetch —
    the read-path helper for enriching a workflow response."""
    required = compute_required_integrations(steps, trigger_config)
    if not required:
        return [], []
    # Deferred to avoid circular import: oauth_service → provisioner → service → here
    from app.services.oauth.oauth_service import get_all_integrations_status

    status_map = await get_all_integrations_status(user_id)
    return build_integration_refs(required, status_map)
