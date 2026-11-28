"""GAIA's first-party connectors: specs the agent never has to draft, run exactly like one it did.

Each entry is a platform integration whose connector_config is an ordinary ConnectorSpec,
so listing, connecting, running, approvals and scrubbing are the connector path itself.
"""

from app.config.connector_catalog.cli import CLI_CONNECTORS
from app.config.connector_catalog.rest import REST_CONNECTORS
from app.config.connector_catalog.row import CatalogRow
from app.config.connector_catalog.sdk import SDK_CONNECTORS
from app.constants.integrations import GOOGLE_FAVICON_URL
from app.models.connector_models import ConnectorSpec
from app.models.oauth_models import OAuthIntegration

_CATEGORY = "developer"


def _entry(row: CatalogRow) -> OAuthIntegration:
    connector = ConnectorSpec.model_validate(row.spec)
    return OAuthIntegration(
        id=row.id,
        name=row.name,
        description=row.description,
        category=_CATEGORY,
        provider=row.id,
        scopes=[],
        managed_by="connector",
        connector_config=connector,
        icon_url=GOOGLE_FAVICON_URL.format(domain=connector.provider_domain),
    )


CONNECTOR_CATALOG: tuple[OAuthIntegration, ...] = tuple(
    _entry(row) for row in (*CLI_CONNECTORS, *REST_CONNECTORS, *SDK_CONNECTORS)
)
