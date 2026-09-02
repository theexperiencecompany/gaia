"""Connecting a CLI integration: one idempotent step at a time.

Connecting a CLI is not a redirect — it is a short-lived process (install the
tool, log it in, confirm the login took) whose duration is dominated by things
GAIA does not control: an npm install, and a human walking to their phone to
approve a device code.

The flow is therefore modelled as a **state machine with no state of its own**.
:func:`advance` is idempotent: each call reads the truth from the sandbox
(is the CLI installed? does it consider itself logged in? is a login still
polling?), takes at most one action, and reports where things stand. The client
calls it repeatedly until it reports a terminal phase.

Deriving the state instead of storing it is what makes this survive the things
that actually happen in production: the sandbox is recreated roughly hourly
(so "installed" must be re-read, never remembered), a replica can be replaced
mid-flow (so no in-process task may own the progress), and a token can be
revoked upstream at any time (so "connected" must mean the CLI says so now, not
that it once did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from e2b import AsyncSandbox

from app.constants.cli_integrations import LOGIN_TIMEOUT_SECONDS
from app.constants.log_tags import LogTag
from app.db.repositories.user_integrations import user_integration_repository
from app.models.cli_config import CliConfig
from app.services.cli import runtime
from app.services.integrations.user_integration_status import update_user_integration_status
from app.services.integrations.user_integrations import add_user_integration
from app.services.sandbox import acquire_sandbox
from shared.py.wide_events import log

# ``installing`` — the CLI is being fetched into the sandbox.
# ``needs_token`` — waiting for the user to paste a secret.
# ``awaiting_approval`` — a device login is live; ``instructions`` says what to do.
# ``connected`` / ``failed`` — terminal.
CliConnectPhase = Literal["installing", "needs_token", "awaiting_approval", "connected", "failed"]

_TERMINAL: frozenset[CliConnectPhase] = frozenset({"connected", "failed"})


@dataclass(frozen=True)
class CliConnectOutcome:
    """Where a connect attempt stands after one :func:`advance` call."""

    phase: CliConnectPhase
    message: str | None = None
    # The login command's own output, relayed verbatim. For a device login this
    # is the URL and code the user needs. Never parsed — see runtime.start_login.
    instructions: str | None = None
    # Prompt copy for the token shape, so the client need not know the config.
    token_label: str | None = None
    token_help_url: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.phase in _TERMINAL


async def advance(
    user_id: str,
    integration_id: str,
    config: CliConfig,
    *,
    token: str | None = None,
) -> CliConnectOutcome:
    """Move one step toward a connected CLI, and report where it stands.

    Safe to call repeatedly and concurrently: every branch is either a read or
    an idempotent write, so a duplicate call costs a round trip and changes
    nothing.
    """
    log.set(
        integration={"id": integration_id, "managed_by": "cli", "action": "cli_connect"},
        cli={"command": config.command, "auth_kind": config.auth.kind},
    )
    # The record must exist before the first status transition, and a user may
    # reach a platform CLI integration without ever having "added" it. Guarded
    # on existence rather than blindly added: this function is the client's poll
    # loop, and ``add_user_integration`` raises on a duplicate, so an unguarded
    # add fails every call after the first.

    if not await user_integration_repository.exists(user_id, integration_id):
        await add_user_integration(user_id, integration_id, initial_status="created")

    async with acquire_sandbox(user_id) as sbx:
        if token is not None:
            written = await runtime.write_token(sbx, integration_id, config, token)
            if not written.ok:
                return _failed(
                    integration_id,
                    "The CLI rejected that token.",
                    detail=written.stderr or written.stdout,
                )

        state = await runtime.probe_state(sbx, integration_id, config)

        if state.install_error:
            return _failed(
                integration_id,
                f"Could not install {config.command}.",
                detail=state.install_error,
            )

        if state.authenticated:
            await update_user_integration_status(user_id, integration_id, "connected")
            log.set(outcome="connected")
            return CliConnectOutcome(phase="connected")

        if config.auth.kind == "none":
            # Nothing to log into, yet the CLI does not report itself ready —
            # a broken install rather than a missing credential.
            return _failed(
                integration_id,
                f"{config.command} is installed but not reporting as ready.",
            )

        if config.auth.kind == "token":
            # A token was just written and the CLI still says no: report that
            # plainly rather than silently asking for the same token again.
            if token is not None:
                return _failed(
                    integration_id,
                    f"{config.command} did not accept that token.",
                )
            return CliConnectOutcome(
                phase="needs_token",
                token_label=config.auth.token_label,
                token_help_url=config.auth.token_help_url,
            )

        return await _advance_device_login(sbx, integration_id, config, state)


async def _advance_device_login(
    sbx: AsyncSandbox,
    integration_id: str,
    config: CliConfig,
    state: runtime.CliState,
) -> CliConnectOutcome:
    """Drive the device-code shape: start a login, or report the live one.

    Two CLI behaviours have to be handled by the same code, because both exist
    in the wild: one keeps a process alive polling the vendor
    (``link-cli auth login --interval``), the other prints the code and exits,
    leaving the exchange to the next status call. Neither is detectable from
    the output, so liveness alone never decides — an already-printed login
    stays on screen until it is old enough to have expired.
    """
    age = state.login_age_seconds
    login_is_fresh = age is not None and age < LOGIN_TIMEOUT_SECONDS

    if state.login_running or (login_is_fresh and state.login_output):
        return CliConnectOutcome(
            phase="awaiting_approval",
            instructions=state.login_output or None,
            message="Waiting for you to approve the login.",
        )

    if login_is_fresh and not state.login_output:
        # Started moments ago and has not printed yet (vendor CLIs take a few
        # seconds to reach their device endpoint). Keep the client polling
        # rather than starting a second login.
        return CliConnectOutcome(
            phase="awaiting_approval", message=f"Starting {config.command} login…"
        )

    started = await runtime.start_login(sbx, integration_id, config)
    if not started.ok:
        return _failed(
            integration_id,
            f"Could not start the {config.command} login.",
            detail=started.stderr or started.stdout,
        )
    return CliConnectOutcome(phase="awaiting_approval", message=f"Starting {config.command} login…")


async def disconnect(user_id: str, integration_id: str, config: CliConfig) -> None:
    """Log the CLI out and remove everything it installed for this user."""
    log.set(integration={"id": integration_id, "action": "cli_disconnect"})
    async with acquire_sandbox(user_id) as sbx:
        await runtime.cancel_login(sbx, integration_id)
        await runtime.clear_credentials(sbx, integration_id, config)


async def is_connected(user_id: str, integration_id: str, config: CliConfig) -> bool:
    """Ask the CLI itself whether it is still logged in."""
    async with acquire_sandbox(user_id) as sbx:
        state = await runtime.probe_state(sbx, integration_id, config)
        return state.authenticated


def _failed(integration_id: str, message: str, *, detail: str | None = None) -> CliConnectOutcome:
    """A terminal failure, logged with the underlying detail.

    The detail is surfaced to the user too: an install or login failure is
    almost always something they can act on (a bad token, a network block),
    and hiding the CLI's own error behind "connection failed" makes it
    unfixable.
    """
    log.set(outcome="failed")
    log.warning(
        f"{LogTag.INTEGRATION} CLI connect failed",
        integration_id=integration_id,
        reason=message,
        detail=(detail or "")[:500],
    )
    return CliConnectOutcome(
        phase="failed",
        message=message,
        instructions=detail.strip() if detail and detail.strip() else None,
    )
