"""Point the integration catalog at another Composio project's auth configs.

Auth config ids belong to one Composio project, and the catalog hardcodes
production's; a local key on a dev project mints links against configs that do
not exist there. Every reader of an auth config id goes through the catalog, so
swapping the ids where it is built covers links, callbacks, webhooks and sync.
"""

from collections.abc import Mapping

from app.models.oauth_models import OAuthIntegration


def with_auth_config_overrides(
    integrations: list[OAuthIntegration], overrides: Mapping[str, str]
) -> list[OAuthIntegration]:
    """Return the catalog with each overridden integration on its new auth config; refuse bad entries."""
    composio_ids = {i.id for i in integrations if i.composio_config}
    unknown = sorted(overrides.keys() - composio_ids)
    if unknown:
        raise ValueError(f"COMPOSIO_AUTH_CONFIG_OVERRIDES names no Composio integration: {unknown}")
    blank = sorted(integration_id for integration_id, ac in overrides.items() if not ac.strip())
    if blank:
        raise ValueError(f"COMPOSIO_AUTH_CONFIG_OVERRIDES has an empty auth config id: {blank}")
    return [
        i.model_copy(
            update={
                "composio_config": i.composio_config.model_copy(
                    update={"auth_config_id": overrides[i.id].strip()}
                )
            }
        )
        if i.composio_config and i.id in overrides
        else i
        for i in integrations
    ]
