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

from typing import Literal

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from app.agents.tools.coding._context import get_user_id
from app.constants.log_tags import LogTag
from app.services.integrations.authoring import (
    CliBlueprint,
    McpBlueprint,
    create_integration,
)
from shared.py.wide_events import log


class CustomIntegrationSpec(BaseModel):
    """The model-facing argument schema: one flat field per fact to supply.

    Deliberately flat rather than a discriminated union of an MCP shape and a
    CLI shape, even though that is what the domain actually is: models fill flat
    schemas far more reliably than nested ones, and a malformed nested argument
    costs a whole tool call to discover. The union is reconstructed in
    ``_build_blueprint``, where it is validated properly.
    """

    kind: Literal["mcp", "cli"] = Field(
        description="'mcp' for a hosted MCP server URL; 'cli' for a real command-line tool."
    )
    name: str = Field(description="Display name, e.g. 'GitHub CLI'")
    description: str = Field(description="One sentence on what it lets the user do")
    server_url: str = Field(default="", description="MCP only: the server's https URL")
    command: str = Field(default="", description="CLI only: the executable name, e.g. 'gh'")
    install_command: str = Field(
        default="",
        description=(
            'CLI only: shell that installs it, e.g. "npm install -g some-cli" or a '
            "curl of a release tarball. Runs unprivileged in the user's sandbox."
        ),
    )
    capabilities: list[str] | None = Field(
        default=None,
        description="CLI only: short phrases for what it can do, shown to the user",
    )
    auth_kind: Literal["none", "device", "token"] = Field(
        default="none",
        description=(
            "CLI only: 'device' if it prints a URL/code to approve, 'token' if the user "
            "pastes a secret, 'none' if it needs no credentials."
        ),
    )
    login_command: str = Field(
        default="", description="CLI only: the login command (required for 'device')"
    )
    verify_command: str = Field(
        default="",
        description="CLI only: a command that exits 0 only when signed in, e.g. 'gh auth status'",
    )
    logout_command: str = Field(
        default="", description="CLI only: the logout command, if it has one"
    )
    token_env: str = Field(
        default="",
        description="CLI only, 'token' auth: the env var the tool reads, e.g. 'GH_TOKEN'",
    )
    token_label: str = Field(
        default="", description="CLI only, 'token' auth: what to call the secret in the UI"
    )
    token_help_url: str = Field(
        default="", description="CLI only, 'token' auth: page where the user creates the token"
    )


@tool(args_schema=CustomIntegrationSpec)
async def create_custom_integration(config: RunnableConfig, **fields: object) -> str:
    """Create a new integration for this user from a description of what backs it.

    Research the tool first; read its docs or `--help`; and pass its real
    install and auth commands. Do not guess them.
    """
    # LangChain hands the tool its arguments flat (the schema above is what the
    # model sees), and only the keys the model actually supplied. Re-validating
    # here is what fills the defaults and turns them back into one typed object,
    # so nothing below this line handles fourteen loose parameters.
    spec = CustomIntegrationSpec.model_validate(fields)
    log.set(
        tool={"name": "create_custom_integration", "action": "create"},
        integration={"kind": spec.kind},
    )
    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"

    try:
        blueprint = _build_blueprint(spec)
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
        f"(id: {authored.integration.integration_id}, kind: {spec.kind}).",
    ]
    if authored.note:
        lines.append(authored.note)
    if authored.needs_connection:
        lines.append(
            "Tell the user to open Integrations and click Connect to finish setting it up."
        )
    return " ".join(lines)


def _build_blueprint(spec: CustomIntegrationSpec) -> McpBlueprint | CliBlueprint:
    """Turn the flat tool arguments into the right typed blueprint.

    The flat schema cannot express "these fields are required for a CLI and
    meaningless for an MCP server", so the per-transport requirements are
    checked here, once, before anything is persisted.
    """
    if spec.kind == "mcp":
        if not spec.server_url:
            raise ValueError("an MCP integration needs server_url")
        return McpBlueprint(
            name=spec.name, description=spec.description, server_url=spec.server_url
        )

    missing = [
        field
        for field, value in (
            ("command", spec.command),
            ("install_command", spec.install_command),
            ("verify_command", spec.verify_command),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"a CLI integration needs {', '.join(missing)}")

    return CliBlueprint(
        name=spec.name,
        description=spec.description,
        command=spec.command,
        install_command=spec.install_command,
        capabilities=spec.capabilities or [],
        auth_kind=spec.auth_kind,
        login_command=spec.login_command or None,
        verify_command=spec.verify_command,
        logout_command=spec.logout_command or None,
        token_env=spec.token_env or None,
        token_label=spec.token_label or None,
        token_help_url=spec.token_help_url or None,
    )


tools = [create_custom_integration]
