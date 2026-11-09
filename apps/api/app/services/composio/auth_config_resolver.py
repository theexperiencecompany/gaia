"""Which Composio auth config each integration connects through on this instance.

An auth config id belongs to one Composio project. Per integration the id an
admin stored on this instance wins, then COMPOSIO_AUTH_CONFIG_OVERRIDES, then
the catalog's id, which exists only in GAIA's own project and so counts only
where the deployment says it does. An integration none of these cover is not
set up here. Every reader of an auth config id goes through this module.
"""

from dataclasses import dataclass
from time import monotonic

from pydantic import TypeAdapter

from app.config.composio_auth_configs import check_auth_config_ids
from app.config.oauth_config import all_integrations
from app.config.settings import settings
from app.constants.integrations import ComposioAuthConfigSource
from app.constants.log_tags import LogTag
from app.db.repositories.instance_settings import instance_settings_repository
from app.models.oauth_models import OAuthIntegration
from app.services.runtime.config_updates import (
    COMPOSIO_AUTH_CONFIGS_SCOPE,
    publish_config_update,
)
from shared.py.wide_events import log

AUTH_CONFIGS_SETTING_KEY = "composio_auth_configs"

# Same bound as stored provider credentials: other pods see a save within this.
_CACHE_TTL_SECONDS = 60.0

_STORED_AUTH_CONFIGS = TypeAdapter(dict[str, str])


@dataclass(frozen=True, slots=True)
class ResolvedAuthConfig:
    """The auth config one integration connects through, and where it came from."""

    auth_config_id: str
    source: ComposioAuthConfigSource


_cache: tuple[float, dict[str, str]] | None = None


def composio_integrations() -> list[OAuthIntegration]:
    """Return every integration, code or instance-enabled, that connects through Composio."""
    return [i for i in all_integrations() if i.composio_config]


async def resolve_auth_configs() -> dict[str, ResolvedAuthConfig]:
    """Map each integration that can connect on this instance to its auth config."""
    stored = await _stored_auth_configs()
    overrides = settings.COMPOSIO_AUTH_CONFIG_OVERRIDES
    use_catalog = settings.deployment.catalog_composio_auth_configs
    resolved: dict[str, ResolvedAuthConfig] = {}
    for integration in composio_integrations():
        if integration.id in stored:
            resolved[integration.id] = ResolvedAuthConfig(
                stored[integration.id], ComposioAuthConfigSource.STORED
            )
        elif integration.id in overrides:
            resolved[integration.id] = ResolvedAuthConfig(
                overrides[integration.id].strip(), ComposioAuthConfigSource.ENV
            )
        elif (
            use_catalog
            and integration.composio_config
            and integration.composio_config.auth_config_id
        ):
            resolved[integration.id] = ResolvedAuthConfig(
                integration.composio_config.auth_config_id, ComposioAuthConfigSource.CATALOG
            )
    return resolved


async def auth_config_id_for(integration: OAuthIntegration) -> str | None:
    """Return the auth config id this integration connects through here; None when not set up."""
    resolved = (await resolve_auth_configs()).get(integration.id)
    return resolved.auth_config_id if resolved else None


async def integration_for_auth_config(auth_config_id: str) -> OAuthIntegration | None:
    """Return the integration a Composio auth config id belongs to on this instance."""
    resolved = await resolve_auth_configs()
    return next(
        (
            i
            for i in composio_integrations()
            if (r := resolved.get(i.id)) and r.auth_config_id == auth_config_id
        ),
        None,
    )


async def save_auth_configs(auth_configs: dict[str, str]) -> None:
    """Replace the instance's stored auth config ids; refuse ones that could never connect."""
    if not settings.deployment.runtime_credentials:
        raise RuntimeError(
            "This deployment reads Composio auth configs from the environment only; "
            "the instance store is not writable here"
        )
    check_auth_config_ids(all_integrations(), auth_configs, origin="The auth config list")
    cleaned = {integration_id: ac.strip() for integration_id, ac in auth_configs.items()}
    await _write_stored(cleaned)


async def set_stored_auth_config(integration_id: str, auth_config_id: str) -> None:
    """Store one integration's auth config id, keeping every other stored entry."""
    if not settings.deployment.runtime_credentials:
        raise RuntimeError("This deployment reads Composio auth configs from the environment only")
    stored = await _read_stored()
    check_auth_config_ids(
        all_integrations(), {integration_id: auth_config_id}, origin="The auth config"
    )
    await _write_stored({**stored, integration_id: auth_config_id.strip()})


async def remove_stored_auth_config(integration_id: str) -> None:
    """Drop one integration's stored auth config id; a missing entry is a no-op."""
    stored = await _read_stored()
    if integration_id in stored:
        await _write_stored({k: v for k, v in stored.items() if k != integration_id})


async def _write_stored(auth_configs: dict[str, str]) -> None:
    await instance_settings_repository.set_value(AUTH_CONFIGS_SETTING_KEY, dict(auth_configs))
    invalidate_auth_config_cache()
    await publish_config_update(COMPOSIO_AUTH_CONFIGS_SCOPE)
    log.info(
        f"{LogTag.COMPOSIO} Composio auth configs saved",
        integration_count=len(auth_configs),
    )


def invalidate_auth_config_cache() -> None:
    """Drop this pod's cached stored set so the next resolve re-reads it; other pods via the subscriber."""
    global _cache
    _cache = None


async def _stored_auth_configs() -> dict[str, str]:
    if not settings.deployment.runtime_credentials:
        return {}
    global _cache
    if _cache is not None and monotonic() - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    stored = await _read_stored()
    _cache = (monotonic(), stored)
    return stored


async def _read_stored() -> dict[str, str]:
    doc = await instance_settings_repository.find_by_key(AUTH_CONFIGS_SETTING_KEY)
    return _STORED_AUTH_CONFIGS.validate_python(doc.value) if doc else {}
