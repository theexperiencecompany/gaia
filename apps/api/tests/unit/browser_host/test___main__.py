"""Tests for the python -m app.browser_host entrypoint.

The entrypoint's whole job is wiring: hand the browser-host FastAPI app to
uvicorn on the configured bind/port with logging left to the app. Running the
module under __main__ with uvicorn.run faked pins that the guard fires
and that the exact app + address flow through -- a swapped host/port here would
publish the internal-only host on the wrong interface.
"""

from __future__ import annotations

import runpy
from unittest.mock import patch

import pytest

from app.browser_host.server import app
from app.config.settings import settings


@pytest.mark.unit
class TestBrowserHostEntrypoint:
    def test_runs_uvicorn_with_the_app_on_configured_bind_and_port(self) -> None:
        with patch("uvicorn.run") as mock_run:
            runpy.run_module("app.browser_host", run_name="__main__")
        mock_run.assert_called_once()
        (passed_app,), kwargs = mock_run.call_args
        assert passed_app is app
        assert kwargs["host"] == settings.BROWSER_HOST_BIND
        assert kwargs["port"] == settings.BROWSER_HOST_PORT
        assert kwargs["log_config"] is None

    def test_does_not_run_uvicorn_on_plain_import(self) -> None:
        # The ``if __name__ == "__main__"`` guard must keep a normal import inert;
        # importing the module for its ``app`` should never boot a server.
        with patch("uvicorn.run") as mock_run:
            runpy.run_module("app.browser_host", run_name="not_main")
        mock_run.assert_not_called()
