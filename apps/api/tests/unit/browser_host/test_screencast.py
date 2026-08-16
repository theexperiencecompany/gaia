"""Live-view screencast setup must never strand a viewer slot.

Regression: ``add_viewer`` sat outside the try/finally, so a failure during
live-view setup (e.g. the CDP client cannot connect) left ``viewer_count`` > 0
forever. The idle reaper skips sessions with viewers, so that session was never
reclaimed — a permanent capacity leak that only a host restart cleared.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import screencast


@pytest.mark.unit
async def test_run_live_view_removes_viewer_when_setup_fails() -> None:
    host = MagicMock()
    host.root_ws_url = "ws://fake-host"
    session = MagicMock()
    session.session_id = "sess-1"

    failing_cdp = MagicMock()
    failing_cdp.start = AsyncMock(side_effect=RuntimeError("cannot reach chromium"))
    failing_cdp.stop = AsyncMock()

    with patch.object(screencast, "CDPClient", return_value=failing_cdp):
        with pytest.raises(RuntimeError):
            await screencast.run_live_view(host, session, MagicMock())

    # The viewer registration must be balanced even though setup blew up, or the
    # session can never be reaped.
    host.add_viewer.assert_called_once_with("sess-1")
    host.remove_viewer.assert_called_once_with("sess-1")
