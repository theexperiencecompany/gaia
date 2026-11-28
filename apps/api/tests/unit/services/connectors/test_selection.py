"""Which runner a call gets, and the error a self-host instance with no sandbox shows."""

import pytest

from app.constants.connectors import CONNECTOR_NO_SANDBOX_MESSAGE
from app.services.connectors import selection
from app.services.connectors.docker_runner import DockerConnectorRunner
from app.services.connectors.e2b_runner import E2BConnectorRunner
from app.services.connectors.selection import (
    ConnectorRunnerUnavailableError,
    get_connector_runner,
)
from app.services.sandbox.errors import CodeExecutionDisabledError


def _local(value: bool | Exception) -> object:
    async def use_local_sandbox() -> bool:
        if isinstance(value, Exception):
            raise value
        return value

    return use_local_sandbox


async def test_a_local_sandbox_instance_runs_connectors_in_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selection, "use_local_sandbox", _local(True))

    assert isinstance(await get_connector_runner(), DockerConnectorRunner)


async def test_an_e2b_instance_runs_connectors_in_e2b(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection, "use_local_sandbox", _local(False))

    assert isinstance(await get_connector_runner(), E2BConnectorRunner)


async def test_an_instance_without_any_sandbox_says_how_to_add_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selection, "use_local_sandbox", _local(CodeExecutionDisabledError()))

    with pytest.raises(ConnectorRunnerUnavailableError) as raised:
        await get_connector_runner()
    assert str(raised.value) == CONNECTOR_NO_SANDBOX_MESSAGE
