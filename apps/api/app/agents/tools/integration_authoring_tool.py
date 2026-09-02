"""Let the agent create an integration the catalog does not have yet.

The UI's "add integration" dialog is deliberately MCP-only: pasting a server URL
is something a user can reasonably do themselves, while describing a CLI (what
installs it, what its login command is, how to tell whether it worked) is
research, not data entry. That research is exactly what an agent is good at -
read the tool's docs, find its install command and its auth shape; so the
multi-transport path lives here rather than in a form.

The agent proposes; the user still has to connect it, which is where anything
actually runs.
"""

from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from pydantic import ValidationError

from app.agents.tools.coding._context import get_user_id
from app.constants.log_tags import LogTag
from app.services.integrations.authoring import (
    CliBlueprint,
    McpBlueprint,
    create_integration,
)
from shared.py.wide_events import log


@tool
async def create_custom_integration(
    config: RunnableConfig,
    kind: Annotated[
        Literal["mcp", "cli"],
        "'mcp' for a hosted MCP server URL; 'cli' for a real command-line tool.",
    ],
    name: Annotated[str, "Display name, e.g. 'GitHub CLI'"],
    description: Annotated[str, "One sentence on what it lets the user do"],
    server_url: Annotated[str, "MCP only: the server's https URL"] = "",
    command: Annotated[str, "CLI only: the executable name, e.g. 'gh'"] = "",
    install_command: Annotated[
        str,
        'CLI only: shell that installs it, e.g. "npm install -g some-cli" or a '
        "curl of a release tarball. Runs unprivileged in the user's sandbox.",
    ] = "",
    capabilities: Annotated[
        list[str] | None, "CLI only: short phrases for what it can do, shown to the user"
    ] = None,
    auth_kind: Annotated[
        Literal["none", "device", "token"],
        "CLI only: 'device' if it prints a URL/code to approve, 'token' if the user "
        "pastes a secret, 'none' if it needs no credentials.",
    ] = "none",
    login_command: Annotated[str, "CLI only: the login command (required for 'device')"] = "",
    verify_command: Annotated[
        str, "CLI only: a command that exits 0 only when signed in, e.g. 'gh auth status'"
    ] = "",
    logout_command: Annotated[str, "CLI only: the logout command, if it has one"] = "",
    token_env: Annotated[
        str, "CLI only, 'token' auth: the env var the tool reads, e.g. 'GH_TOKEN'"
    ] = "",
    token_label: Annotated[str, "CLI only, 'token' auth: what to call the secret in the UI"] = "",
    token_help_url: Annotated[
        str, "CLI only, 'token' auth: page where the user creates the token"
    ] = "",
) -> str:
    """Create a new integration for this user from a description of what backs it.

    Research the tool first; read its docs or `--help`; and pass its real
    install and auth commands. Do not guess them.
    """
    log.set(
        tool={"name": "create_custom_integration", "action": "create"}, integration={"kind": kind}
    )
    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"

    try:
        blueprint = _build_blueprint(
            kind=kind,
            name=name,
            description=description,
            server_url=server_url,
            command=command,
            install_command=install_command,
            capabilities=capabilities or [],
            auth_kind=auth_kind,
            login_command=login_command,
            verify_command=verify_command,
            logout_command=logout_command,
            token_env=token_env,
            token_label=token_label,
            token_help_url=token_help_url,
        )
    except (ValidationError, ValueError) as e:
        # Returned rather than raised: the caller is a model that can read the
        # complaint and retry with the field it left out.
        return f"Could not create the integration; {e}"

    try:
        authored = await create_integration(user_id, blueprint)
    except ValueError as e:
        return f"Could not create the integration; {e}"
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Authoring an integration failed",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return f"Error creating the integration: {e}"

    lines = [
        f"Created '{authored.integration.name}' "
        f"(id: {authored.integration.integration_id}, kind: {kind}).",
    ]
    if authored.note:
        lines.append(authored.note)
    if authored.needs_connection:
        lines.append(
            "Tell the user to open Integrations and click Connect to finish setting it up."
        )
    return " ".join(lines)


def _build_blueprint(
    *,
    kind: str,
    name: str,
    description: str,
    server_url: str,
    command: str,
    install_command: str,
    capabilities: list[str],
    auth_kind: str,
    login_command: str,
    verify_command: str,
    logout_command: str,
    token_env: str,
    token_label: str,
    token_help_url: str,
) -> McpBlueprint | CliBlueprint:
    """Turn the tool's flat arguments into the right typed blueprint.

    Flat arguments rather than a nested union because models fill flat schemas
    far more reliably; the union is reconstructed here where it can be
    validated properly.
    """
    if kind == "mcp":
        if not server_url:
            raise ValueError("an MCP integration needs server_url")
        return McpBlueprint(name=name, description=description, server_url=server_url)

    missing = [
        field
        for field, value in (
            ("command", command),
            ("install_command", install_command),
            ("verify_command", verify_command),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"a CLI integration needs {', '.join(missing)}")

    return CliBlueprint(
        name=name,
        description=description,
        command=command,
        install_command=install_command,
        capabilities=capabilities,
        auth_kind=auth_kind,  # type: ignore[arg-type]  # validated by the Literal on the tool arg
        login_command=login_command or None,
        verify_command=verify_command,
        logout_command=logout_command or None,
        token_env=token_env or None,
        token_label=token_label or None,
        token_help_url=token_help_url or None,
    )


tools = [create_custom_integration]
