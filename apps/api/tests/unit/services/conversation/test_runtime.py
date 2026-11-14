"""runtime_ports: the ports startup installed, or a loud refusal before it did."""

import pytest

from app.services.conversation import runtime
from app.services.conversation.runtime import (
    RuntimeNotInstalledError,
    install_runtime_ports,
    runtime_ports,
)
from tests.unit.services.conversation.runtime_doubles import Runtime


def test_a_producer_before_startup_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime._Installed, "ports", None)
    with pytest.raises(RuntimeNotInstalledError) as refused:
        runtime_ports()
    assert str(refused.value) == (
        "the conversation runtime was used before startup installed its ports"
    )


def test_every_producer_reaches_the_ports_startup_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime._Installed, "ports", None)
    ports = Runtime().ports
    install_runtime_ports(ports)
    assert runtime_ports() is ports
