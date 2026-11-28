"""The device cards' payloads: pairing a computer with GAIA, and approving its pairing code."""

from app.schemas.common import ResponseModel


class CliInstallCommands(ResponseModel):
    """The GAIA CLI's install command per package manager."""

    npm: str
    pnpm: str
    bun: str


class DeviceOnboardingCard(ResponseModel):
    """The device_onboarding_required card: install the CLI, then pair the computer."""

    install_commands: CliInstallCommands
    docs_url: str
    pair_command: str
    up_command: str
    message: str


class DeviceApprovalCard(ResponseModel):
    """The device_approval_required card: the approve page for a pairing code."""

    approve_url: str
    code: str
    message: str
