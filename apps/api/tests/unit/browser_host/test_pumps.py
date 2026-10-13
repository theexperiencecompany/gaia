"""Tests for the shared bidirectional websocket pump.

pump_until_first_close backs both the CDP proxy and the screencast bridge:
it must stop the instant either direction ends, swallow an ordinary peer
disconnect, but re-raise a real error so the caller's teardown sees it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import cast

from fastapi import WebSocketDisconnect
import pytest
from starlette.websockets import WebSocket, WebSocketState
from websockets.exceptions import ConnectionClosed

from app.browser_host import pumps
from app.browser_host.pumps import is_disconnect, pump_until_first_close

# Safety timeout for pumps that should return promptly. If `asyncio.wait`'s
# return_when were mutated to ALL_COMPLETED, a never-ending pump direction
# would hang the pump forever instead of returning on the first completion.
_TIMEOUT = 1.0


async def _instant_return() -> None:
    return None


async def _instant_raise(exc: BaseException) -> None:
    raise exc


async def _blocks_forever() -> None:
    await asyncio.Event().wait()


def _socket(
    client: WebSocketState = WebSocketState.CONNECTED,
    application: WebSocketState = WebSocketState.CONNECTED,
) -> WebSocket:
    return cast(WebSocket, SimpleNamespace(client_state=client, application_state=application))


_NOT_CONNECTED = RuntimeError('WebSocket is not connected. Need to call "accept" first.')


@pytest.mark.unit
class TestIsDisconnect:
    def test_a_peer_close_on_either_side_is_a_disconnect(self) -> None:
        assert is_disconnect(ConnectionClosed(None, None)) is True
        assert is_disconnect(WebSocketDisconnect()) is True

    def test_classifies_in_an_interpreter_that_never_imported_the_submodule(
        self, tmp_path: Path
    ) -> None:
        """Import websockets alone does not bind websockets.exceptions on 15.x, so a real script file is needed since the mutation gate's trampoline resolves the caller's filename strictly."""
        probe = tmp_path / "probe.py"
        probe.write_text(
            "from app.browser_host.pumps import is_disconnect\n"
            "print(is_disconnect(RuntimeError('x')))\n"
        )
        # The package root of the module under test, so the probe imports the
        # same `app` this process did (the mutants copy under the mutation gate).
        package_root = Path(pumps.__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            check=False,
            text=True,
            env={**os.environ, "ENV": "development", "PYTHONPATH": str(package_root)},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"

    @pytest.mark.parametrize("closed_side", ["client", "application"])
    def test_a_use_after_close_error_is_a_disconnect_only_once_a_socket_has_closed(
        self, closed_side: str
    ) -> None:
        closed = (
            _socket(client=WebSocketState.DISCONNECTED)
            if closed_side == "client"
            else _socket(application=WebSocketState.DISCONNECTED)
        )

        assert is_disconnect(_NOT_CONNECTED, [_socket(), closed]) is True
        assert is_disconnect(_NOT_CONNECTED, [_socket()]) is False
        assert is_disconnect(_NOT_CONNECTED) is False

    def test_another_error_is_never_a_disconnect(self) -> None:
        closed = [_socket(client=WebSocketState.DISCONNECTED)]

        assert is_disconnect(ValueError("boom"), closed) is False

        class _OddRuntimeError(RuntimeError):
            pass

        assert is_disconnect(_OddRuntimeError("x"), closed) is False


@pytest.mark.unit
class TestPumpUntilFirstClose:
    async def test_returns_as_soon_as_one_direction_finishes(self) -> None:
        """The other direction never completes on its own; the pump must not wait for it."""
        await asyncio.wait_for(
            pump_until_first_close(_instant_return(), _blocks_forever()),
            timeout=_TIMEOUT,
        )

    async def test_real_error_from_one_direction_is_re_raised(self) -> None:
        with pytest.raises(ValueError, match="boom"):
            await asyncio.wait_for(
                pump_until_first_close(_instant_raise(ValueError("boom")), _blocks_forever()),
                timeout=_TIMEOUT,
            )

    async def test_a_closed_viewers_use_after_close_error_exits_cleanly(self) -> None:
        closed = _socket(client=WebSocketState.DISCONNECTED)

        await pump_until_first_close(
            _instant_raise(_NOT_CONNECTED), _blocks_forever(), sockets=[closed]
        )

    async def test_ordinary_disconnect_is_swallowed_not_raised(self) -> None:
        disconnect = ConnectionClosed(None, None)
        await asyncio.wait_for(
            pump_until_first_close(_instant_raise(disconnect), _blocks_forever()),
            timeout=_TIMEOUT,
        )

    async def test_real_error_wins_even_when_another_direction_finished_cleanly(self) -> None:
        """Both directions complete before asyncio.wait returns; the error must still surface."""
        with pytest.raises(RuntimeError, match="second failed"):
            await asyncio.wait_for(
                pump_until_first_close(
                    _instant_return(), _instant_raise(RuntimeError("second failed"))
                ),
                timeout=_TIMEOUT,
            )

    async def test_pending_direction_is_cancelled_after_the_other_closes(self) -> None:
        """The direction that never finishes on its own must be torn down, not leaked."""
        pending_task_ref: list[asyncio.Task[None]] = []

        async def _blocks_and_records(task_holder: list[asyncio.Task[None]]) -> None:
            running = asyncio.current_task()
            assert running is not None  # we are inside it
            task_holder.append(running)
            await asyncio.Event().wait()

        await asyncio.wait_for(
            pump_until_first_close(_instant_return(), _blocks_and_records(pending_task_ref)),
            timeout=_TIMEOUT,
        )

        assert len(pending_task_ref) == 1
        assert pending_task_ref[0].cancelled()
