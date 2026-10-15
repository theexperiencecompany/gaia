"""Enable a Composio toolkit on this instance: create its auth config and wire it in.

A toolkit GAIA defines in code gets the auth config stored under that
integration, which replaces creating one by hand in the Composio dashboard.
Any other toolkit is also stored as an instance toolkit, so it joins the
integration catalog with generic config.
"""

from dataclasses import dataclass
from typing import cast

import composio_client
from composio_client.types.auth_config_create_params import (
    AuthConfig,
    AuthConfigUnionMember0,
    AuthConfigUnionMember1,
)
from composio_client.types.toolkit_retrieve_response import ToolkitRetrieveResponse

from app.agents.tools.core.registry import get_tool_registry
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.cache import ALL_USERS_TOOLS_CACHE_PATTERN
from app.constants.log_tags import LogTag
from app.decorators.caching import CacheInvalidator
from app.models.oauth_models import OAuthIntegration
from app.schemas.integrations.composio_setup import (
    ComposioAuthField,
    ComposioCatalogEntry,
    ComposioToolkitDetailResponse,
    EnableComposioToolkitResponse,
)
from app.services.composio.auth_config_resolver import (
    remove_stored_auth_config,
    set_stored_auth_config,
)
from app.services.composio.auth_config_setup import composio_key_rejected
from app.services.composio.composio_service import get_composio_service
from app.services.composio.instance_toolkits import (
    InstanceToolkitRecord,
    remove_toolkit,
    save_toolkit,
)
from app.services.composio.toolkit_catalog import annotate, cached_toolkits
from app.utils.background_tasks import spawn_background_task
from app.utils.errors import AppError
from shared.py.wide_events import log

_NO_AUTH = "NO_AUTH"
_PREFERRED_MANAGED_SCHEME = "OAUTH2"


@dataclass(frozen=True, slots=True)
class AuthPlan:
    """How GAIA will create a toolkit's auth config; scheme None means it cannot."""

    scheme: str | None
    composio_managed: bool
    fields: list[ComposioAuthField]


def plan_auth(toolkit: ToolkitRetrieveResponse) -> AuthPlan:
    """Prefer Composio's own app; otherwise the first scheme that needs sign-in, with its fields."""
    managed = toolkit.composio_managed_auth_schemes or []
    if managed:
        scheme = _PREFERRED_MANAGED_SCHEME if _PREFERRED_MANAGED_SCHEME in managed else managed[0]
        return AuthPlan(scheme=scheme, composio_managed=True, fields=[])
    detail = next((d for d in toolkit.auth_config_details or [] if d.mode != _NO_AUTH), None)
    if detail is None:
        return AuthPlan(scheme=None, composio_managed=False, fields=[])
    creation = detail.fields.auth_config_creation
    fields = [
        ComposioAuthField(
            name=f.name,
            display_name=f.display_name,
            description=f.description,
            required=required,
            is_secret=bool(f.is_secret),
        )
        for required, group in ((True, creation.required), (False, creation.optional))
        for f in group
    ]
    return AuthPlan(scheme=detail.mode, composio_managed=False, fields=fields)


def _auth_options(name: str, plan: AuthPlan, credentials: dict[str, str]) -> AuthConfig:
    label = f"GAIA {name}"
    if plan.composio_managed:
        return AuthConfigUnionMember0(type="use_composio_managed_auth", name=label)
    missing = [
        f.display_name
        for f in plan.fields
        if f.required and not credentials.get(f.name, "").strip()
    ]
    if missing:
        raise AppError(
            message=f"{name} needs {', '.join(missing)} to create its auth config",
            fix="Fill in every required field and enable it again",
            status_code=422,
            code="composio_auth_fields_missing",
            public={"missing_fields": missing},
        )
    known = {f.name for f in plan.fields}
    supplied = {k: v.strip() for k, v in credentials.items() if k in known and v.strip()}
    options: dict[str, object] = {
        "type": "use_custom_auth",
        "auth_scheme": plan.scheme,
        "name": label,
    }
    if supplied:
        options["credentials"] = supplied
    # plan.scheme is a Composio auth_config_details mode, so a member of the Literal;
    # credentials beyond the TypedDict's scopes are stored as sent (verified live).
    return cast(AuthConfigUnionMember1, options)


async def _entry(slug: str) -> ComposioCatalogEntry:
    summary = next((t for t in await cached_toolkits() if t.slug == slug), None)
    if summary is None:
        raise AppError(
            message=f"Composio has no toolkit {slug!r}",
            status_code=404,
            code="composio_toolkit_not_found",
        )
    return (await annotate([summary]))[0]


async def _retrieve(slug: str) -> ToolkitRetrieveResponse:
    try:
        return await get_composio_service().get_toolkit(slug)
    except composio_client.AuthenticationError as e:
        raise composio_key_rejected(e) from e


async def toolkit_detail(slug: str) -> ComposioToolkitDetailResponse:
    """Return how enabling the toolkit authenticates and which values it needs."""
    entry = await _entry(slug)
    plan = plan_auth(await _retrieve(slug))
    return ComposioToolkitDetailResponse(
        toolkit=entry,
        auth_scheme=plan.scheme,
        composio_managed=plan.composio_managed,
        fields=plan.fields,
    )


def _code_integration(slug: str) -> OAuthIntegration | None:
    return next(
        (
            i
            for i in OAUTH_INTEGRATIONS
            if i.composio_config and i.composio_config.toolkit.lower() == slug
        ),
        None,
    )


async def enable_toolkit(slug: str, credentials: dict[str, str]) -> EnableComposioToolkitResponse:
    """Create the toolkit's auth config and make it connectable on this instance."""
    entry = await _entry(slug)
    plan = plan_auth(await _retrieve(slug))
    if plan.scheme is None:
        raise AppError(
            message=f"{entry.name} needs no sign-in, which GAIA cannot connect yet",
            status_code=422,
            code="composio_toolkit_unsupported",
        )
    options = _auth_options(entry.name, plan, credentials)
    try:
        auth_config_id = await get_composio_service().create_auth_config(slug, options)
    except composio_client.AuthenticationError as e:
        raise composio_key_rejected(e) from e
    except composio_client.BadRequestError as e:
        raise AppError(
            message=f"Composio refused to create an auth config for {entry.name}",
            why=str(e),
            status_code=422,
            code="composio_auth_config_rejected",
        ) from e

    integration = await _install(entry, plan.scheme, auth_config_id)
    log.set_ns(
        "composio_toolkit",
        slug=slug,
        integration_id=integration.id,
        origin=integration.origin,
        composio_managed=plan.composio_managed,
        auth_scheme=plan.scheme,
    )
    return EnableComposioToolkitResponse(
        integration_id=integration.id,
        auth_config_id=auth_config_id,
        origin=integration.origin,
        composio_managed=plan.composio_managed,
    )


# Invalidates when the writes start, so it wraps only the fast Mongo writes:
# a page read during the slow Composio call before it would re-cache the old list.
@CacheInvalidator(key=ALL_USERS_TOOLS_CACHE_PATTERN)
async def _install(
    entry: ComposioCatalogEntry, scheme: str, auth_config_id: str
) -> OAuthIntegration:
    integration = _code_integration(entry.slug)
    if integration is None:
        integration = await save_toolkit(
            InstanceToolkitRecord(
                slug=entry.slug,
                name=entry.name,
                description=entry.description,
                logo=entry.logo,
                category=entry.categories[0] if entry.categories else "other",
                auth_scheme=scheme,
            )
        )
        spawn_background_task(_index_toolkit_tools(integration))
    await set_stored_auth_config(integration.id, auth_config_id)
    return integration


@CacheInvalidator(key=ALL_USERS_TOOLS_CACHE_PATTERN)
async def disable_toolkit(slug: str) -> None:
    """Remove a toolkit the admin enabled; its Composio auth config is left in their project."""
    if not await remove_toolkit(slug):
        raise AppError(
            message=f"{slug!r} is not a toolkit enabled on this instance",
            status_code=404,
            code="composio_toolkit_not_enabled",
        )
    await remove_stored_auth_config(slug)


async def _index_toolkit_tools(integration: OAuthIntegration) -> None:
    """Index the toolkit's tools for retrieval; the index is shared, so one pod does it."""
    registry = await get_tool_registry()
    indexed = await registry.populate_provider_catalog([integration])
    log.info(
        f"{LogTag.TOOL} Indexed an enabled Composio toolkit",
        integration_id=integration.id,
        tool_count=indexed,
    )
