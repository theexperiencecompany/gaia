"""Check a set of Composio auth config ids against the integration catalog.

Auth config ids belong to one Composio project and the catalog declares
production's; a non-production instance supplies its own per integration, from
COMPOSIO_AUTH_CONFIG_OVERRIDES or the admin's stored set. Which one wins is
app.services.composio.auth_config_resolver's call; this only refuses entries
that could never connect.
"""

from collections.abc import Mapping, Sequence

from app.models.oauth_models import OAuthIntegration


def check_auth_config_ids(
    integrations: Sequence[OAuthIntegration], auth_configs: Mapping[str, str], *, origin: str
) -> None:
    """Raise ValueError when an entry names no Composio integration or has a blank id."""
    composio_ids = {i.id for i in integrations if i.composio_config}
    unknown = sorted(auth_configs.keys() - composio_ids)
    if unknown:
        raise ValueError(f"{origin} names no Composio integration: {unknown}")
    blank = sorted(integration_id for integration_id, ac in auth_configs.items() if not ac.strip())
    if blank:
        raise ValueError(f"{origin} has an empty auth config id: {blank}")
