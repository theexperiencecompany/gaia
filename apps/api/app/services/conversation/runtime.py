"""The conversation runtime's ports as every producer reaches them, installed once by the composition root.

Producers (sends, the executor, approvals, stops, the sweeper) append through these ports;
they never build them, so none of them imports the comms graph or the work it cancels.
"""

from dataclasses import dataclass

from app.constants.conversation import ConversationRuntime
from app.db.repositories.conversations import conversation_repository
from app.services.conversation.ports import RuntimePorts
from app.utils.errors import AppError


@dataclass
class RuntimeNotInstalledError(AppError):
    """A producer reached the conversation runtime before the process installed it."""


class _Installed:
    ports: RuntimePorts | None = None


def install_runtime_ports(ports: RuntimePorts) -> None:
    """Make ports the ones every producer in this process appends through."""
    _Installed.ports = ports


def runtime_ports() -> RuntimePorts:
    """Return the installed ports; raise when startup never installed them."""
    if _Installed.ports is None:
        raise RuntimeNotInstalledError(
            message="the conversation runtime was used before startup installed its ports"
        )
    return _Installed.ports


async def runs_on_step(conversation_id: str, user_id: str) -> bool:
    """Return whether the conversation step runs this conversation; False for a missing one."""
    row = await conversation_repository.read_runtime(conversation_id, user_id=user_id)
    return row is not None and row.runtime is ConversationRuntime.STEP
