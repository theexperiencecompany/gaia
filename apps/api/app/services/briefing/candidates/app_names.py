"""The display name of a built-in integration a candidate came from, and back."""

from app.config.oauth_config import all_integrations, get_integration_by_id


def integration_name(integration_id: str) -> str:
    """Return the integration's display name; raise for an id the catalog does not hold."""
    integration = get_integration_by_id(integration_id)
    if integration is None:
        raise KeyError(f"no integration {integration_id!r} in the catalog")
    return integration.name


def integration_id_named(name: str) -> str | None:
    """Return the id of the integration displayed as name; None for a name no integration carries."""
    return next((i.id for i in all_integrations() if i.name == name), None)
