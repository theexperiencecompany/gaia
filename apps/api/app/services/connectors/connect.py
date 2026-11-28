"""Connect a connector: prove the user's key with the spec's verify call, then store it."""

from datetime import UTC, datetime
import json
import re

from app.constants.integrations import IntegrationStatus
from app.constants.log_tags import LogTag
from app.db.repositories.integrations import integration_repository
from app.models.connector_models import ConnectorSpec, IdentityExtractor
from app.models.integration_models import (
    Integration,
    IntegrationAccount,
    IntegrationUpdate,
    new_account_id,
)
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.analytics_service import capture
from app.services.connectors.selection import ConnectorRunnerUnavailableError
from app.services.connectors.service import (
    CallFailure,
    ConnectorNotFoundError,
    load_connector,
    run_with_secret,
)
from app.services.integrations.integration_accounts import save_accounts
from app.services.integrations.user_integration_status import publish_connected
from app.services.integrations.user_integrations import (
    invalidate_user_integration_caches,
    remove_user_integration,
)
from app.services.mcp.mcp_token_store import MCPTokenStore
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnectorVerifyFailed
from shared.py.wide_events import log

# Shown when the verify call proves the key but its output names no account.
_UNNAMED_ACCOUNT = "your account"
_IDENTITY_MAX_CHARS = 80


def extract_identity(extractor: IdentityExtractor, stdout: str) -> str | None:
    """Return the account the verify output names, by JSON dot path or regex group."""
    if extractor.json_path:
        try:
            value: object = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        for key in extractor.json_path.split("."):
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
                value = value[int(key)]
            else:
                return None
        return str(value)[:_IDENTITY_MAX_CHARS] if isinstance(value, str | int) else None
    if extractor.regex:
        match = re.search(extractor.regex, stdout)
        return match.group(1)[:_IDENTITY_MAX_CHARS] if match else None
    return None


def failure_copy(name: str, spec: ConnectorSpec, failure: CallFailure) -> str:
    """Say in plain words why the key could not be verified and what fixes it."""
    where = f" from {spec.credential.token_url}" if spec.credential.token_url else ""
    match failure:
        case CallFailure.AUTH:
            return (
                f"{name} refused this {spec.credential.label}. Copy the whole key{where} "
                "and check it hasn't expired or been revoked."
            )
        case CallFailure.INSTALL:
            return f"GAIA couldn't install {name}'s tools, so it couldn't check the key. Try again shortly."
        case CallFailure.TIMEOUT:
            return f"{name} took too long to answer, so the key isn't verified yet. Try again."
        case CallFailure.RUNNER:
            return "GAIA has no sandbox to run this connector in right now. Try again shortly."
        case CallFailure.EXIT:
            return (
                f"GAIA couldn't sign in to {name} with this key. Check it has read access"
                f"{where} and try again."
            )


def _error(connector_id: str, name: str, message: str) -> ConnectIntegrationResponse:
    return ConnectIntegrationResponse(
        status="error", integration_id=connector_id, name=name, error=message
    )


async def connect_connector(
    user_id: str, connector_id: str, secret: str | None
) -> ConnectIntegrationResponse:
    """Verify the key in a throwaway runner; on success store it and the account it names."""
    if not secret or not secret.strip():
        return _error(connector_id, connector_id, "Paste the key to connect")
    try:
        doc, spec = await load_connector(user_id, connector_id)
    except ConnectorNotFoundError:
        return _error(connector_id, connector_id, f"Integration {connector_id} not found")
    try:
        return await _verify_and_store(user_id, doc, spec, secret.strip())
    except ConnectorRunnerUnavailableError as e:
        log.warning(f"{LogTag.INTEGRATION} No sandbox to verify a connector key", user_id=user_id)
        return _error(connector_id, doc.name, str(e))


async def _verify_and_store(
    user_id: str, doc: Integration, spec: ConnectorSpec, secret: str
) -> ConnectIntegrationResponse:
    connector_id = doc.integration_id
    log.set_ns("connector", id=connector_id, action="connect", kind=spec.kind)
    result = await run_with_secret(spec, spec.verify.args, secret)
    if result.failure is not None:
        log.set_ns("connector", verify="failed", failure=result.failure)
        capture(
            UserId(user_id),
            IntegrationConnectorVerifyFailed(
                integration_id=connector_id, kind=spec.kind.value, reason=result.failure.value
            ),
        )
        return _error(connector_id, doc.name, failure_copy(doc.name, spec, result.failure))
    identity = extract_identity(spec.verify.identity, result.stdout) or _UNNAMED_ACCOUNT
    await MCPTokenStore(user_id).store_bearer_token(connector_id, secret)
    account = IntegrationAccount(
        id=new_account_id(),
        connected_account_id=connector_id,
        identity={"account": identity},
        label=identity,
    )
    await save_accounts(user_id, connector_id, [account], account.id)
    if doc.connector_verified_at is None:
        await integration_repository.update(
            connector_id, IntegrationUpdate(connector_verified_at=datetime.now(UTC))
        )
    await invalidate_user_integration_caches(user_id)
    await publish_connected(user_id, connector_id)
    log.set_ns("connector", verify="ok", status=IntegrationStatus.CONNECTED)
    log.info(f"{LogTag.INTEGRATION} Connector connected", connector_id=connector_id)
    return ConnectIntegrationResponse(
        status="connected",
        integration_id=connector_id,
        name=doc.name,
        message=f"Connected as {identity}",
        account_label=identity,
    )


async def disconnect_connector(user_id: str, connector_id: str) -> None:
    """Forget the user's key and the account it named; the connector stays to reconnect."""
    await MCPTokenStore(user_id).delete_credentials(connector_id)
    await remove_user_integration(user_id, connector_id)
    log.set_ns("connector", id=connector_id, action="disconnect")
