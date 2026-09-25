"""Tests for the python -m app.browser_host entrypoint.

The entrypoint's whole job is wiring: hand the browser-host FastAPI app to
uvicorn on the configured bind/port with logging left to the app. main() is
called through its package path so the exact app + address it passes are pinned
-- a swapped host/port here would publish the internal-only host on the wrong
interface -- and one run under __main__ pins that the script guard fires.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess  # nosec B404
import sys
from unittest.mock import patch

import pytest

from app.browser_host import __main__ as entrypoint
from app.browser_host.server import app
from app.config.browser_host_settings import browser_host_settings


@pytest.mark.unit
class TestBrowserHostEntrypoint:
    def test_runs_uvicorn_with_the_app_on_configured_bind_and_port(self) -> None:
        with (
            patch("uvicorn.run") as mock_run,
            patch.object(entrypoint, "configure_file_logging"),
        ):
            entrypoint.main()
        mock_run.assert_called_once()
        (passed_app,), kwargs = mock_run.call_args
        assert passed_app is app
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8930
        assert kwargs["log_config"] is None

    def test_the_image_bind_address_reaches_uvicorn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_BIND_ADDRESS", "10.0.0.7")
        with (
            patch("uvicorn.run") as mock_run,
            patch.object(entrypoint, "configure_file_logging"),
        ):
            entrypoint.main()
        assert mock_run.call_args.kwargs["host"] == "10.0.0.7"

    def test_running_the_module_as_a_script_serves_the_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # python -m app.browser_host is how the image starts the host, so the
        # ``__main__`` guard must hand off to main(). A fresh run, as the
        # interpreter does it: not over the copy the other tests imported.
        monkeypatch.delitem(sys.modules, "app.browser_host.__main__")
        with (
            patch("uvicorn.run") as mock_run,
            patch("shared.py.logging.configure_file_logging"),
        ):
            runpy.run_module("app.browser_host", run_name="__main__")
        (passed_app,), _ = mock_run.call_args
        assert passed_app is app

    def test_does_not_run_uvicorn_on_plain_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The ``if __name__ == "__main__"`` guard must keep a normal import inert;
        # importing the module for its ``app`` should never boot a server.
        monkeypatch.delitem(sys.modules, "app.browser_host.__main__")
        with patch("uvicorn.run") as mock_run:
            runpy.run_module("app.browser_host", run_name="not_main")
        mock_run.assert_not_called()

    def test_boots_in_production_without_the_app_settings(self) -> None:
        """The host renders attacker pages, so it must never load the Infisical-backed settings."""
        probe = (
            "import sys, app.browser_host.__main__; sys.exit('app.config.settings' in sys.modules)"
        )
        env = {"PATH": os.environ["PATH"], "ENV": "production"}
        result = subprocess.run(  # nosec B603 -- fixed argv
            [sys.executable, "-c", probe], env=env, capture_output=True, check=False
        )
        assert result.returncode == 0, result.stderr.decode()[-2000:]

    def test_names_itself_and_writes_local_log_files_like_the_api_and_worker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GAIA_SERVICE_NAME", raising=False)
        with (
            patch("uvicorn.run"),
            patch.object(entrypoint, "configure_file_logging") as file_logging,
        ):
            entrypoint.main()
        assert os.environ["GAIA_SERVICE_NAME"] == "browser-host"
        file_logging.assert_called_once_with("./logs/browser-host")

    def test_its_lines_reach_stdout_as_json_under_its_own_service_name(self) -> None:
        """What Promtail scrapes from the container: one JSON object per line, labelled browser-host."""
        probe = (
            "import runpy, uvicorn; from shared.py.wide_events import log; "
            "uvicorn.run = lambda *a, **k: log.error('probe', error_type='Probe'); "
            "runpy.run_module('app.browser_host', run_name='__main__')"
        )
        env = {"PATH": os.environ["PATH"], "ENV": "production", "LOG_FORMAT": "json"}
        result = subprocess.run(  # nosec B603 -- fixed argv
            [sys.executable, "-c", probe], env=env, capture_output=True, check=False
        )
        assert result.returncode == 0, result.stderr.decode()[-2000:]
        lines = [json.loads(line) for line in result.stdout.decode().splitlines() if line]
        [probe_line] = [line for line in lines if line["message"] == "probe"]
        assert probe_line["service"] == "browser-host"
        assert probe_line["error_type"] == "Probe"
