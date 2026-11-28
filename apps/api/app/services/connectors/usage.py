"""The usage notes activation loads for a connector: how to call it and what asks first."""

from app.constants.connectors import RUN_CONNECTOR_TOOL
from app.models.connector_models import ConnectorKind, ConnectorSpec
from app.models.integration_models import Integration


def _call_shape(spec: ConnectorSpec) -> str:
    match spec.kind:
        case ConnectorKind.CLI:
            return (
                f"args are the arguments after `{spec.command}`, one list item per argument "
                f'(e.g. ["api", "user"]), never one shell string; no pipes, no redirects.'
            )
        case ConnectorKind.REST:
            base = spec.rest.base_url if spec.rest else ""
            return (
                f'args are METHOD PATH [--query k=v]... [--json BODY] [--header K:V]..., e.g. ["GET", '
                f'"/v1/items", "--query", "limit=10"]. PATH is relative to {base}; the key is added for you.'
            )
        case ConnectorKind.SDK:
            return (
                f"args run the {spec.sdk_runtime} interpreter with its installed packages, e.g. "
                '["-c", "<script>"]; the key is already in the environment the SDK reads.'
            )


def render_connector_usage(doc: Integration, spec: ConnectorSpec) -> str:
    """Return the connector's operating notes for the agent's context."""
    lines = [
        f"## {doc.name}: how to use it",
        doc.description or spec.capability,
        f'Run it with execute(tool_name="{RUN_CONNECTOR_TOOL}", data={{"connector_id": '
        f'"{doc.integration_id}", "args": [...]}}), or gaia.execute from a script.',
        _call_shape(spec),
        "Each call runs in a fresh sandbox holding the key for that call only; nothing persists "
        "between calls, so pass everything a call needs in its args.",
        f"It can reach only: {', '.join(spec.allowed_hosts)}.",
        "Reads run at once. A call that changes something asks the user the first time for each "
        "kind of change. Output never contains the key; never try to print or reveal it.",
    ]
    if spec.kind is ConnectorKind.CLI and spec.usage.help_args:
        lines.append(f"Help: args {spec.usage.help_args}.")
    if spec.usage.json_flag:
        lines.append(f"Ask for JSON output with {spec.usage.json_flag}.")
    if spec.usage.guidance:
        lines.append(spec.usage.guidance)
    return "\n".join(lines)
