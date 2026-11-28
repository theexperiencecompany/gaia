"""Which runner a connector call uses: E2B where a key resolves, local docker on self-host without one."""

from app.constants.connectors import CONNECTOR_NO_SANDBOX_MESSAGE
from app.services.connectors.docker_runner import DockerConnectorRunner
from app.services.connectors.e2b_runner import E2BConnectorRunner
from app.services.connectors.runner import ConnectorRunner
from app.services.sandbox.errors import CodeExecutionDisabledError
from app.services.sandbox.lifecycle import use_local_sandbox


class ConnectorRunnerUnavailableError(RuntimeError):
    """Raised when the instance has no sandbox a connector call could run in."""

    def __init__(self) -> None:
        super().__init__(CONNECTOR_NO_SANDBOX_MESSAGE)


async def get_connector_runner() -> ConnectorRunner:
    """Return the runner for this instance, decided per call so a saved E2B key applies at once."""
    try:
        local = await use_local_sandbox()
    except CodeExecutionDisabledError as error:
        raise ConnectorRunnerUnavailableError from error
    return DockerConnectorRunner() if local else E2BConnectorRunner()
