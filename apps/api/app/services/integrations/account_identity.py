"""Who a connected account is on its provider (email, handle, workspace) and the label it goes by."""

import asyncio
import json

from pydantic import BaseModel, JsonValue

from app.constants.integrations import FALLBACK_ACCOUNT_LABEL
from app.models.oauth_models import OAuthIntegration
from app.services.composio.composio_service import get_composio_service
from shared.py.wide_events import log


class _ToolResult(BaseModel):
    data: JsonValue = None
    successful: bool = False
    error: str | None = None


def _as_object(data: JsonValue) -> dict[str, JsonValue]:
    # Composio answers some profile tools with the body JSON-encoded as a string.
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError(f"profile response is {type(data).__name__}, not an object")
    return data


def _extract(data: dict[str, JsonValue], field_path: str) -> str | None:
    value: JsonValue = data
    for key in field_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return None if value is None else str(value)


async def fetch_account_identity(
    user_id: str, integration: OAuthIntegration, connected_account_id: str
) -> dict[str, str]:
    """Call the integration's profile tools as this account and extract the configured variables."""
    if integration.metadata_config is None:
        return {}
    composio = get_composio_service().composio
    identity: dict[str, str] = {}
    for tool_config in integration.metadata_config.tools:
        raw = await asyncio.to_thread(
            composio.tools.execute,
            slug=tool_config.tool,
            arguments={},
            user_id=user_id,
            connected_account_id=connected_account_id,
            dangerously_skip_version_check=True,
        )
        result = _ToolResult.model_validate(raw)
        if not result.successful:
            raise RuntimeError(f"{tool_config.tool} failed: {result.error}")
        data = _as_object(result.data)
        for variable in tool_config.variables:
            value = _extract(data, variable.field_path)
            if value:
                identity[variable.name] = value
    log.set_ns("account_identity", integration_id=integration.id, fields=sorted(identity))
    return identity


def account_label(integration: OAuthIntegration, identity: dict[str, str], taken: set[str]) -> str:
    """Name an account from its identity, or number it when the provider exposes none."""
    if integration.metadata_config is not None and identity:
        try:
            return integration.metadata_config.label_template.format_map(identity)
        except KeyError as missing:
            log.warning(
                "account_label_template_missing_field",
                integration_id=integration.id,
                missing=str(missing),
            )
    number = len(taken) + 1
    while (
        label := FALLBACK_ACCOUNT_LABEL.format(integration=integration.name, number=number)
    ) in taken:
        number += 1
    return label
