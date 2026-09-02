"""Connecting an integration backed by a real command-line tool."""

from __future__ import annotations

from typing import ClassVar, Literal

from app.models.integration_provider import ManagedBy
from app.schemas.integrations.responses import CliConnectDetail, ConnectIntegrationResponse
from app.services.cli import advance
from app.services.cli.connect import CliConnectOutcome
from app.services.integrations.providers.base import ConnectContext, IntegrationProvider


class CliIntegrationProvider(IntegrationProvider):
    """Drives the CLI connect state machine one step per call.

    Unlike the OAuth transports, this returns ``pending`` for as long as the
    work takes — an install, then a human approving a device code — and the
    client re-POSTs until it does not. There is no redirect to hand off to and
    no callback to wait on: the CLI is being driven inside the user's own
    sandbox, so GAIA is the one holding the progress.
    """

    managed_by: ClassVar[ManagedBy] = "cli"

    async def connect(self, ctx: ConnectContext) -> ConnectIntegrationResponse:
        config = ctx.resolved.cli_config
        if config is None:
            # The catalog validator pins cli_config for managed_by="cli", so
            # this means a hand-written Mongo document rather than a code path.
            return self.error(ctx, f"{ctx.integration_id} has no CLI configuration")

        outcome = await advance(ctx.user_id, ctx.integration_id, config, token=ctx.secret or None)
        return _to_response(ctx, outcome)


def _to_response(ctx: ConnectContext, outcome: CliConnectOutcome) -> ConnectIntegrationResponse:
    """Map the connect state machine's outcome onto the shared response shape."""
    detail = CliConnectDetail(
        phase=outcome.phase,
        instructions=outcome.instructions,
        token_label=outcome.token_label,
        token_help_url=outcome.token_help_url,
    )
    status: Literal["connected", "error", "pending"]
    if outcome.phase == "connected":
        status = "connected"
    elif outcome.phase == "failed":
        status = "error"
    else:
        status = "pending"

    return ConnectIntegrationResponse(
        status=status,
        integration_id=ctx.integration_id,
        name=ctx.resolved.name,
        message=outcome.message,
        error=outcome.message if outcome.phase == "failed" else None,
        cli=detail,
    )
