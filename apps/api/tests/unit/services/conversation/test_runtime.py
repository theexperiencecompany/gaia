"""runtime_ports: the one set of ports every producer appends through, refused before startup installs it."""

import pytest

from app.services.conversation import runtime
from app.services.conversation.runtime import (
    RuntimeNotInstalledError,
    install_runtime_ports,
    runtime_ports,
)
from tests.unit.services.conversation.runtime_doubles import Runtime


def test_a_producer_before_startup_is_told_the_runtime_is_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime._Installed, "ports", None)

    with pytest.raises(RuntimeNotInstalledError) as refused:
        runtime_ports()

    assert refused.value.message == (
        "the conversation runtime was used before startup installed its ports"
    )


def test_the_installed_ports_are_the_ones_every_producer_reaches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime._Installed, "ports", None)
    ports = Runtime().ports

    install_runtime_ports(ports)

    assert runtime_ports() is ports
