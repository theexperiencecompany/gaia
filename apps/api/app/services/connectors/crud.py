"""Create or update a user's connector from a spec, keeping a published connector's reach honest."""

from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

from app.constants.connectors import MANAGED_BY_CONNECTOR, RUN_CONNECTOR_TOOL
from app.constants.integrations import IntegrationStatus
from app.constants.log_tags import LogTag
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.models.connector_models import ConnectorSpec
from app.models.integration_models import Integration, IntegrationUpdate, StoredIntegrationTool
from app.services.analytics_service import capture
from app.services.integrations.user_integration_status import update_user_integration_status
from app.services.integrations.user_integrations import (
    add_user_integration,
    invalidate_user_integration_caches,
)
from app.utils.favicon_utils import fetch_favicon_from_url
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnectorDefined
from shared.py.wide_events import log

_CONNECTOR_CATEGORY = "developer"
# Why another user's connection stops when the creator changes where the key can go.
REACH_CHANGED_REASON = "The connector's hosts or packages changed; reconnect to approve them"


def _tools(spec: ConnectorSpec) -> list[StoredIntegrationTool]:
    return [StoredIntegrationTool(name=RUN_CONNECTOR_TOOL, description=spec.capability)]


async def _expire_other_users(doc: Integration, owner_id: str) -> None:
    """Make every other user of a published connector re-approve it before their key travels further."""
    for user_id in await user_integration_repository.user_ids_with_integration(doc.integration_id):
        if user_id != owner_id:
            await update_user_integration_status(
                user_id,
                doc.integration_id,
                IntegrationStatus.EXPIRED,
                expired_reason=REACH_CHANGED_REASON,
            )


@dataclass(frozen=True)
class DefinedConnector:
    doc: Integration
    created: bool
    reach_changed: bool


async def _update_existing(
    existing: Integration, user_id: str, name: str, description: str, spec: ConnectorSpec
) -> DefinedConnector:
    old_spec = existing.connector_config
    reach_changed = old_spec is None or old_spec.reach_fingerprint() != spec.reach_fingerprint()
    update = IntegrationUpdate(
        name=name,
        description=description,
        connector_config=spec,
        updated_at=datetime.now(UTC),
        connector_verified_at=None if reach_changed else existing.connector_verified_at,
    )
    updated = await integration_repository.update(existing.integration_id, update)
    if updated is None:
        raise LookupError(f"connector {existing.integration_id} vanished during update")
    await integration_repository.store_tools(existing.integration_id, _tools(spec))
    if reach_changed and existing.is_public:
        await _expire_other_users(existing, user_id)
    log.set_ns(
        "connector", id=existing.integration_id, action="update", reach_changed=reach_changed
    )
    return DefinedConnector(doc=updated, created=False, reach_changed=reach_changed)


async def define_connector(
    user_id: str, name: str, description: str, spec: ConnectorSpec
) -> DefinedConnector:
    """Upsert the user's private connector for the spec's provider and add it to their workspace."""
    existing = await integration_repository.find_custom_connector(user_id, spec.provider_domain)
    if existing is not None:
        defined = await _update_existing(existing, user_id, name, description, spec)
    else:
        defined = await _create(user_id, name, description, spec)
    capture(
        UserId(user_id),
        IntegrationConnectorDefined(
            integration_id=defined.doc.integration_id,
            kind=spec.kind.value,
            created=defined.created,
            reach_changed=defined.reach_changed,
        ),
    )
    return defined


async def _create(
    user_id: str, name: str, description: str, spec: ConnectorSpec
) -> DefinedConnector:
    doc = Integration(
        integration_id=str(uuid.uuid4()),
        name=name,
        description=description,
        category=_CONNECTOR_CATEGORY,
        managed_by=MANAGED_BY_CONNECTOR,
        source="custom",
        is_public=False,
        created_by=user_id,
        connector_config=spec,
        requires_auth=True,
        auth_type="bearer",
        tools=_tools(spec),
        icon_url=await fetch_favicon_from_url(f"https://{spec.provider_domain}"),
        display_priority=0,
        is_featured=False,
        published_at=None,
        clone_count=0,
        created_at=datetime.now(UTC),
    )
    await integration_repository.create(doc)
    try:
        await add_user_integration(
            user_id, doc.integration_id, initial_status=IntegrationStatus.CREATED
        )
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Failed to add the connector to the workspace, rolling back",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        await integration_repository.delete(doc.integration_id)
        raise
    await invalidate_user_integration_caches(user_id)
    log.set_ns("connector", id=doc.integration_id, action="create", kind=spec.kind)
    return DefinedConnector(doc=doc, created=True, reach_changed=False)
