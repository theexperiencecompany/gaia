"""Composio toolkits this instance's admin enabled beyond the code catalog.

Stored as one instance_settings document; each record becomes an OAuthIntegration
with a generic in-context config and joins the catalog through
oauth_config.set_instance_integrations. Loaded at startup by the API and the
worker, and again on every runtime-config update, so all pods see a save.
"""

from pydantic import BaseModel, TypeAdapter

from app.agents.prompts.subagent_prompts import composio_toolkit_system_prompt
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_toolkit,
    set_instance_integrations,
)
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.repositories.instance_settings import instance_settings_repository
from app.models.mcp_config import ComposioConfig, SubAgentConfig
from app.models.oauth_models import OAuthIntegration
from app.services.runtime.config_updates import INSTANCE_TOOLKITS_SCOPE, publish_config_update
from shared.py.wide_events import log

TOOLKITS_SETTING_KEY = "composio_toolkits"

# Composio's own category for toolkits it files under none.
UNCATEGORISED_TOOLKIT_CATEGORY = "other"


class InstanceToolkitRecord(BaseModel):
    """What the instance keeps about one enabled toolkit; the auth config id lives in the auth config store."""

    slug: str
    name: str
    description: str
    logo: str | None = None
    category: str = UNCATEGORISED_TOOLKIT_CATEGORY
    auth_scheme: str


_STORED_TOOLKITS = TypeAdapter(dict[str, InstanceToolkitRecord])


def build_instance_integration(record: InstanceToolkitRecord) -> OAuthIntegration:
    """Turn a stored toolkit into a Composio integration with generic, in-context config."""
    return OAuthIntegration(
        id=record.slug,
        name=record.name,
        description=record.description,
        category=record.category,
        provider=record.slug,
        scopes=[],
        managed_by="composio",
        origin="instance",
        icon_url=record.logo,
        composio_config=ComposioConfig(auth_config_id=None, toolkit=record.slug.upper()),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name=f"{record.slug}_agent",
            tool_space=record.slug,
            domain=record.name,
            capabilities=record.description,
            use_cases=f"working with {record.name}",
            system_prompt=composio_toolkit_system_prompt(record.name, record.description),
        ),
    )


def shadows_code_integration(slug: str) -> bool:
    """Whether a toolkit slug is already a code integration's id or toolkit."""
    lowered = slug.lower()
    return any(
        i.id == lowered
        or (i.composio_config is not None and i.composio_config.toolkit.lower() == lowered)
        for i in OAUTH_INTEGRATIONS
    )


async def stored_toolkits() -> dict[str, InstanceToolkitRecord]:
    """Return every stored toolkit record keyed by slug; empty where the deployment has none."""
    if not settings.deployment.instance_toolkits:
        return {}
    doc = await instance_settings_repository.find_by_key(TOOLKITS_SETTING_KEY)
    return _STORED_TOOLKITS.validate_python(doc.value) if doc else {}


async def load_instance_toolkits() -> None:
    """Install the stored toolkits into this pod's integration catalog."""
    records = await stored_toolkits()
    # A toolkit GAIA later ships in code takes over: the stored auth config is
    # keyed by the same id, so connections keep working through the code entry.
    shadowed = sorted(slug for slug in records if shadows_code_integration(slug))
    if shadowed:
        log.warning(
            f"{LogTag.COMPOSIO} Instance toolkits now defined in code; using the code entries",
            toolkits=shadowed,
        )
    set_instance_integrations(
        [
            build_instance_integration(record)
            for slug, record in sorted(records.items())
            if slug not in shadowed
        ]
    )
    log.set_ns("instance_toolkits", loaded=len(records) - len(shadowed))


async def save_toolkit(record: InstanceToolkitRecord) -> OAuthIntegration:
    """Persist one toolkit, apply it on this pod and tell the others; return its integration."""
    if shadows_code_integration(record.slug):
        raise ValueError(f"{record.slug!r} is already a built-in integration")
    records = await stored_toolkits()
    await _write({**records, record.slug: record})
    integration = get_integration_by_toolkit(record.slug)
    if integration is None:
        raise RuntimeError(f"Toolkit {record.slug!r} was saved but did not load")
    return integration


async def remove_toolkit(slug: str) -> bool:
    """Drop one toolkit; return False when it was not enabled."""
    records = await stored_toolkits()
    if slug not in records:
        return False
    await _write({k: v for k, v in records.items() if k != slug})
    return True


async def _write(records: dict[str, InstanceToolkitRecord]) -> None:
    if not settings.deployment.instance_toolkits:
        raise RuntimeError("This deployment does not enable Composio toolkits at runtime")
    await instance_settings_repository.set_value(
        TOOLKITS_SETTING_KEY, {slug: r.model_dump() for slug, r in records.items()}
    )
    await load_instance_toolkits()
    await publish_config_update(INSTANCE_TOOLKITS_SCOPE)
