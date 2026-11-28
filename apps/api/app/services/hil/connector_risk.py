"""How the HIL gate sees a run_connector call: its remembered-approval key, and whether it writes."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.constants.connectors import CONNECTOR_HIL_KEY_PREFIX, RUN_CONNECTOR_TOOL
from app.services.connectors.commands import InvalidConnectorCallError, plan_call
from app.services.connectors.service import ConnectorNotFoundError, load_connector


@dataclass(frozen=True)
class ConnectorCallRisk:
    # connector:<connector id>:<command type>; one "always allow" covers exactly this.
    key: str
    is_write: bool


def connector_hil_key(connector_id: str, command_type: str) -> str:
    return f"{CONNECTOR_HIL_KEY_PREFIX}{connector_id}:{command_type}"


async def connector_call_risk(
    user_id: str, tool_name: str, args: Mapping[str, object] | None
) -> ConnectorCallRisk | None:
    """Classify a run_connector call by its connector's spec; None for any other tool or an unrunnable call."""
    if tool_name != RUN_CONNECTOR_TOOL or not args:
        return None
    connector_id = args.get("connector_id")
    call_args = args.get("argv")
    if not isinstance(connector_id, str) or not isinstance(call_args, list):
        return None
    if not all(isinstance(arg, str) for arg in call_args):
        return None
    try:
        _, spec = await load_connector(user_id, connector_id)
        plan = plan_call(spec, [str(arg) for arg in call_args])
    except (ConnectorNotFoundError, InvalidConnectorCallError):
        # The tool itself refuses these calls before anything runs.
        return None
    return ConnectorCallRisk(
        key=connector_hil_key(connector_id, plan.command_type), is_write=plan.is_write
    )
