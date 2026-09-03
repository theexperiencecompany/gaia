"""CLI-backed integrations: running real vendor command-line tools for a user.

``runtime`` owns the sandbox mechanics (install, launcher, execution);
``connect`` owns the idempotent connect state machine built on top of it.
"""

from app.models.cli_config import CliConnectPhase
from app.services.cli.connect import CliConnectOutcome, advance, disconnect
from app.services.cli.runtime import CliResult, CliState

__all__ = [
    "CliConnectOutcome",
    "CliConnectPhase",
    "CliResult",
    "CliState",
    "advance",
    "disconnect",
]
