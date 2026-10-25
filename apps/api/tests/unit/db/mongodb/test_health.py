"""ping_mongodb round-trips the server's ping command and surfaces a server that does not answer."""

from typing import Any

import pytest

from app.db.mongodb import health


class _FakeDatabase:
    def __init__(self, error: Exception | None = None) -> None:
        self.commands: list[str] = []
        self._error = error

    async def command(self, name: str) -> dict[str, Any]:
        self.commands.append(name)
        if self._error is not None:
            raise self._error
        return {"ok": 1.0}


async def test_the_probe_sends_the_ping_command(monkeypatch: pytest.MonkeyPatch) -> None:
    database = _FakeDatabase()
    monkeypatch.setattr(health, "get_async_database", lambda: database)

    await health.ping_mongodb()

    assert database.commands == ["ping"]


async def test_a_server_that_does_not_answer_fails_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = ConnectionRefusedError("mongo:27017 refused")
    monkeypatch.setattr(health, "get_async_database", lambda: _FakeDatabase(refused))

    with pytest.raises(ConnectionRefusedError) as raised:
        await health.ping_mongodb()
    assert raised.value is refused
