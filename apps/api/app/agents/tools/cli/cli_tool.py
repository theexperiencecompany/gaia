"""The agent's handle on a connected CLI: one tool per integration.

Deliberately ONE tool that takes a shell command, rather than a generated tool
per subcommand. A vendor CLI already documents itself; ``--help`` on every
subcommand, and increasingly a machine-readable ``--schema``; and that
documentation is always correct for the installed version. Enumerating
subcommands into fixed tool schemas would freeze a snapshot of it, break on the
vendor's next release, and throw away the long tail (every flag, every
subcommand nobody thought to wrap) which is precisely what makes a CLI worth
integrating.

So the model gets what a developer gets: the command, its own help, and a
shell. Pipes, redirection and ``&&`` work, because a CLI without them is half a
CLI; ``gh pr list --json number | jq ...`` is the normal way to use one.

What the tool does bound is attribution, not isolation: its name, description
and HIL gating belong to one integration, and every command it runs is
classified against that integration. It is NOT a sandbox within the sandbox --
``PATH`` carries the shared launcher directory, so every CLI the user has
connected is reachable from any of them, and they all run as the same sandbox
user. That is the same trust boundary the bash tool already has: one user's
own tools, on one user's own machine.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.agents.tools.coding._context import get_session_id, get_user_id
from app.agents.workspace.paths import session_dir
from app.constants.cli_integrations import (
    CLI_COMMAND_METADATA_KEY,
    CLI_INTEGRATION_METADATA_KEY,
    EXEC_DEFAULT_TIMEOUT_SECONDS,
    EXEC_MAX_COMMAND_LENGTH,
    EXEC_MAX_TIMEOUT_SECONDS,
    INSTALL_TIMEOUT_SECONDS,
    cli_tool_name,
)
from app.constants.log_tags import LogTag
from app.models.cli_config import CliConfig
from app.services.cli import runtime
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.utils.output_limiter import truncate_head_tail
from shared.py.wide_events import log


class CliToolInput(BaseModel):
    """Arguments for one CLI invocation."""

    command: str = Field(
        description=(
            "Shell command to run. The CLI is already on PATH and authenticated. "
            "Pipes, redirection and && are supported."
        )
    )
    timeout: int = Field(
        default=EXEC_DEFAULT_TIMEOUT_SECONDS,
        description="Seconds before the command is killed.",
    )


def _description(config: CliConfig, integration_name: str) -> str:
    """What the model is told this tool is for.

    Names the executable explicitly and points at ``--help`` as the way to
    learn the rest, so discovery happens against the installed version instead
    of against whatever was true when this integration was written.
    """
    lines = [
        f"Run the `{config.command}` command-line tool for {integration_name}. "
        f"It is installed and signed in as the user.",
    ]
    if config.capabilities:
        lines.append("Use it for: " + ", ".join(config.capabilities) + ".")
    lines.append(
        f"You do not know this tool's exact flags; run `{config.command} --help`, "
        f"or `{config.command} <subcommand> --help`, before guessing. "
        "Prefer a JSON/machine-readable output flag when the tool offers one."
    )
    return " ".join(lines)


def build_cli_tool(
    integration_id: str,
    integration_name: str,
    config: CliConfig,
    *,
    is_platform: bool = True,
) -> BaseTool:
    """Create the LangChain tool that runs one connected CLI."""
    name = cli_tool_name(config.command, integration_id, is_platform=is_platform)

    async def _run(
        command: Annotated[str, "Shell command to run"],
        timeout: int = EXEC_DEFAULT_TIMEOUT_SECONDS,
        # Injected by LangChain from the run context (matched on the
        # RunnableConfig annotation), not supplied by the model — it is absent
        # from args_schema, which is what the model actually sees.
        run_config: RunnableConfig | None = None,
    ) -> str:
        runnable_config: RunnableConfig = run_config or {}
        log.set(
            tool={"name": name, "action": "execute"},
            integration={"id": integration_id, "managed_by": "cli"},
        )
        if not command.strip():
            return "Error: command cannot be empty"
        if len(command) > EXEC_MAX_COMMAND_LENGTH:
            return f"Error: command exceeds {EXEC_MAX_COMMAND_LENGTH} characters"

        try:
            user_id = get_user_id(runnable_config)
        except ValueError as e:
            return f"Error: {e}"

        bounded = max(1, min(timeout, EXEC_MAX_TIMEOUT_SECONDS))
        session_id = get_session_id(runnable_config)
        # Run from the session directory so anything the CLI writes (an export,
        # a downloaded file) lands where the rest of the turn's artifacts do.
        cwd = session_dir(session_id) if session_id else None

        try:
            async with acquire_sandbox(user_id) as sbx:
                result = await runtime.execute(
                    sbx,
                    integration_id,
                    config,
                    command,
                    # `bounded` is the model's budget for ITS command. The
                    # install guard shares the same shell, and after the hourly
                    # sandbox recreation the first call pays for it, so the
                    # sandbox-level deadline has to cover both or a cold call
                    # dies mid-install with a timeout the model cannot act on.
                    timeout=bounded + INSTALL_TIMEOUT_SECONDS,
                    cwd=cwd,
                )
        except SandboxAcquisitionError as e:
            return f"Error: sandbox unavailable ({e})"
        except Exception as e:
            log.error(
                f"{LogTag.INTEGRATION} CLI tool failed",
                integration_id=integration_id,
                error_type=type(e).__name__,
                exc_info=True,
            )
            return f"Error running {config.command}: {e}"

        if result.install_failed:
            return (
                f"Error: {config.command} is not installed and could not be installed.\n"
                f"{truncate_head_tail(result.stderr)}"
            )

        parts = [f"exit_code: {result.exit_code}"]
        if result.stdout:
            parts.append("stdout:\n" + truncate_head_tail(result.stdout))
        if result.stderr:
            parts.append("stderr:\n" + truncate_head_tail(result.stderr))
        return "\n\n".join(parts)

    return StructuredTool.from_function(
        coroutine=_run,
        name=name,
        description=_description(config, integration_name),
        args_schema=CliToolInput,
        # The gate reads these to classify the command being run, and to tie the
        # call back to the integration that must be connected for it to work.
        metadata={
            CLI_INTEGRATION_METADATA_KEY: integration_id,
            CLI_COMMAND_METADATA_KEY: config.command,
        },
    )
