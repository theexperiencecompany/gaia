"""Tests for the shared bidirectional websocket pump.

`pump_until_first_close` backs both the CDP proxy and the screencast bridge:
it must stop the instant either direction ends, swallow an ordinary peer
disconnect, but re-raise a real error so the caller's teardown sees it.
"""

from __future__ import annotations

import asyncio

import pytest
import websockets

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


class WebSocketDisconnect(Exception):
    """Stand-in for FastAPI's exception, checked by `is_disconnect` by name only."""


@pytest.mark.unit
class TestIsDisconnect:
    def test_connection_closed_is_a_disconnect(self) -> None:
        assert is_disconnect(websockets.exceptions.ConnectionClosed(None, None)) is True

    def test_websocket_disconnect_by_name_is_a_disconnect(self) -> None:
        assert is_disconnect(WebSocketDisconnect()) is True

    def test_unrelated_exception_type_is_not_a_disconnect(self) -> None:
        assert is_disconnect(ValueError("boom")) is False

    def test_starlette_not_connected_runtimeerror_is_a_disconnect(self) -> None:
        # Starlette raises this bare RuntimeError when a socket is read after it
        # closed / before accept — normal during teardown, not a real error.
        assert (
            is_disconnect(
                RuntimeError('WebSocket is not connected. Need to call "accept" first.')
            )
            is True
        )

    def test_receive_after_disconnect_runtimeerror_is_a_disconnect(self) -> None:
        assert (
            is_disconnect(
                RuntimeError(
                    'Cannot call "receive" once a disconnect message has been received.'
                )
            )
            is True
        )

    def test_an_unrelated_runtimeerror_still_propagates(self) -> None:
        # The match is by exact message, so real RuntimeErrors are not swallowed.
        assert is_disconnect(RuntimeError("second failed")) is False

    def test_similarly_named_exception_is_not_a_disconnect(self) -> None:
        """Pins the exact class-name string, not a prefix/substring match."""

        class WebSocketDisconnected(Exception):
            pass

        assert is_disconnect(WebSocketDisconnected()) is False


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

    async def test_not_connected_runtimeerror_exits_cleanly_not_raised(self) -> None:
        # A viewer socket read during teardown must not blow up the pump.
        err = RuntimeError('WebSocket is not connected. Need to call "accept" first.')
        # returns None (no raise) — the whole point of the fix.
        assert (
            await pump_until_first_close(_instant_raise(err), _blocks_forever())
        ) is None

    async def test_ordinary_disconnect_is_swallowed_not_raised(self) -> None:
        disconnect = websockets.exceptions.ConnectionClosed(None, None)
        await asyncio.wait_for(
            pump_until_first_close(_instant_raise(disconnect), _blocks_forever()),
            timeout=_TIMEOUT,
        )

    async def test_real_error_wins_even_when_another_direction_finished_cleanly(self) -> None:
        """Both directions complete before `asyncio.wait` returns; the error must still surface."""
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
