"""Connector tools: define a connector for any CLI, REST API or SDK, and run one call against it."""

import json
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.connectors import DEFINE_CONNECTOR_TOOL, RUN_CONNECTOR_TOOL
from app.constants.integrations import ConnectMode, IntegrationStatus
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators import with_doc
from app.models.agent_models import agent_configurable
from app.models.connector_models import ConnectorSpec
from app.services.analytics_service import capture
from app.services.connectors.commands import InvalidConnectorCallError
from app.services.connectors.crud import define_connector as save_connector
from app.services.connectors.selection import ConnectorRunnerUnavailableError
from app.services.connectors.service import (
    CallFailure,
    ConnectorCallResult,
    ConnectorNotFoundError,
    load_connector,
    run_with_secret,
)
from app.services.integrations.user_integration_status import update_user_integration_status
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.templates.docstrings.connector_tool_docs import DEFINE_CONNECTOR, RUN_CONNECTOR
from app.utils.integration_checker import request_integration_connection
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnectorCallRan
from shared.py.wide_events import log

_REVOKED_REASON = "The provider refused the stored key"


def _user_id(config: RunnableConfig) -> str:
    user_id = agent_configurable(config).get("user_id")
    if not user_id:
        raise PermissionError("no signed-in user in this run")
    return str(user_id)


def _for_model(result: ConnectorCallResult) -> str:
    body: dict[str, object] = {
        "ok": result.failure is None,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.failure is not None:
        body["failure"] = result.failure
    if result.output_capped:
        body["note"] = "output was cut short; narrow the call (filters, limits, fields)"
    return json.dumps(body, ensure_ascii=False)


async def _expire_if_revoked(
    user_id: str, connector_id: str, name: str, spec: ConnectorSpec, secret: str
) -> str | None:
    """Re-run the verify call after an auth failure; when it fails too, ask the user to reconnect."""
    check = await run_with_secret(spec, spec.verify.args, secret)
    if check.failure is not CallFailure.AUTH:
        return None
    await update_user_integration_status(
        user_id, connector_id, IntegrationStatus.EXPIRED, expired_reason=_REVOKED_REASON
    )
    log.set_ns("connector", expired=True)
    return await request_integration_connection(
        connector_id, name, user_id, mode=ConnectMode.RECONNECT
    )


@tool(RUN_CONNECTOR_TOOL)
@with_doc(RUN_CONNECTOR)
async def run_connector(
    connector_id: Annotated[str, "The connector's integration id."],
    argv: Annotated[
        list[str], "The call's arguments, one item per argument; never a shell string."
    ],
    config: RunnableConfig,
) -> str:
    user_id = _user_id(config)
    log.set(tool={"name": RUN_CONNECTOR_TOOL}, connector={"id": connector_id})
    try:
        doc, spec = await load_connector(user_id, connector_id)
    except ConnectorNotFoundError:
        return f"Unknown connector '{connector_id}'."
    secret = await MCPTokenStore(user_id).get_bearer_token(connector_id)
    connected = await user_integration_repository.is_connected(user_id, connector_id)
    if secret is None or not connected:
        return await request_integration_connection(connector_id, doc.name, user_id)
    try:
        result = await run_with_secret(spec, argv, secret)
    except InvalidConnectorCallError as e:
        return f"Invalid call: {e}"
    except ConnectorRunnerUnavailableError as e:
        return str(e)
    capture(
        UserId(user_id),
        IntegrationConnectorCallRan(
            integration_id=connector_id,
            kind=spec.kind.value,
            is_write=result.is_write,
            ok=result.failure is None,
            failure=result.failure.value if result.failure else None,
            duration_ms=result.duration_ms,
            output_capped=result.output_capped,
        ),
    )
    if result.failure is CallFailure.AUTH:
        if reconnect := await _expire_if_revoked(user_id, connector_id, doc.name, spec, secret):
            return reconnect
    return _for_model(result)


@tool(DEFINE_CONNECTOR_TOOL)
@with_doc(DEFINE_CONNECTOR)
async def define_connector(
    name: Annotated[str, "The service's name as users know it, e.g. 'Fly.io'."],
    description: Annotated[str, "Two sentences: what the service is and what GAIA can do with it."],
    spec: ConnectorSpec,
    config: RunnableConfig,
) -> str:
    user_id = _user_id(config)
    log.set(tool={"name": DEFINE_CONNECTOR_TOOL}, connector={"provider": spec.provider_domain})
    doc = (await save_connector(user_id, name.strip(), description.strip(), spec)).doc
    if await user_integration_repository.is_connected(user_id, doc.integration_id):
        return (
            f"{doc.name} is connected as connector '{doc.integration_id}'. "
            f'Call activate_integration("{doc.integration_id}") to load how to use it.'
        )
    return await request_integration_connection(doc.integration_id, doc.name, user_id)


tools = [run_connector, define_connector]
