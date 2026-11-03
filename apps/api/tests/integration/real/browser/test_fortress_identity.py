"""Every context of the host's one Fortress engine presents one identity, its page agreeing with its headers.

Fortress draws a persona per created context unless every surface is pinned, so
three users on one host would otherwise look like three machines, each sending
headers its own JavaScript contradicts. Linux-only: Fortress ships no macOS build.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import http.server
import json
import sys
import threading
from typing import Any

import pytest

from app.browser_host.cdp_mux import cdp_call
from app.browser_host.host import BrowserHost, HostSession
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import BrowserEngine

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Fortress ships no build for this platform"
)

_CONTEXTS = 3
_ECHO_PATH = "/echo"
_CLIENT_HINTS = (
    "Sec-CH-UA-Platform-Version, Sec-CH-UA-Arch, Sec-CH-UA-Bitness, "
    "Sec-CH-UA-Full-Version-List, Device-Memory"
)
#: Request headers that carry a fingerprint surface; the rest vary per request.
_IDENTITY_HEADERS = (
    "user-agent",
    "accept-language",
    "sec-ch-ua",
    "sec-ch-ua-platform",
    "sec-ch-ua-platform-version",
    "sec-ch-ua-arch",
    "sec-ch-ua-bitness",
    "sec-ch-ua-full-version-list",
)
#: Every pinned surface the page can read, then the headers its own fetch sent.
_READ_IDENTITY = (
    """(async () => {
  const gl = document.createElement('canvas').getContext('webgl');
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  const he = await navigator.userAgentData.getHighEntropyValues(
    ['platform', 'platformVersion', 'architecture', 'bitness', 'fullVersionList']);
  const speech = typeof speechSynthesis;
  if (speech === 'undefined') return JSON.stringify({page: {speech}, headers: {}});
  if (!speechSynthesis.getVoices().length) {
    await new Promise(r => { speechSynthesis.onvoiceschanged = r; setTimeout(r, 2500); });
  }
  const battery = await navigator.getBattery();
  const page = {
    speech, ua: navigator.userAgent, platform: navigator.platform, languages: navigator.languages,
    cores: navigator.hardwareConcurrency, memory: navigator.deviceMemory, he,
    brands: navigator.userAgentData.brands, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: [screen.width, screen.height, screen.availWidth, screen.availHeight, devicePixelRatio],
    outer: [outerWidth, outerHeight], battery: [battery.charging, battery.level],
    gl: [gl.getParameter(info.UNMASKED_VENDOR_WEBGL), gl.getParameter(info.UNMASKED_RENDERER_WEBGL),
         gl.getParameter(gl.MAX_TEXTURE_SIZE)],
    quota: (await navigator.storage.estimate()).quota,
    media: (await navigator.mediaDevices.enumerateDevices()).map(d => d.kind),
    voices: speechSynthesis.getVoices().map(v => [v.name, v.lang, v.localService, v.default]),
  };
  const headers = await (await fetch('"""
    + _ECHO_PATH
    + """?' + Math.random())).json();
  return JSON.stringify({page, headers});
})()"""
)
_LOADED = "location.origin + '|' + document.readyState"
_LOAD_POLLS = 100
_LOAD_POLL_SECONDS = 0.1


async def _read_identity(session: HostSession, origin: str) -> dict[str, Any]:
    """Load the echo page in the session's tab, then read the identity it presents."""
    await cdp_call(
        session.mux, "Page.navigate", {"url": f"{origin}/"}, session_id=session.page_session
    )
    for _ in range(_LOAD_POLLS):
        loaded = await cdp_call(
            session.mux,
            "Runtime.evaluate",
            {"expression": _LOADED, "returnByValue": True},
            session_id=session.page_session,
        )
        if loaded["result"].get("value") == f"{origin}|complete":
            break
        await asyncio.sleep(_LOAD_POLL_SECONDS)
    else:
        pytest.fail(f"the echo page never loaded in context {session.context_id}")
    result = await cdp_call(
        session.mux,
        "Runtime.evaluate",
        {"expression": _READ_IDENTITY, "returnByValue": True, "awaitPromise": True},
        session_id=session.page_session,
    )
    assert "exceptionDetails" not in result, result["exceptionDetails"]
    identity: dict[str, Any] = json.loads(result["result"]["value"])
    return identity


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    """Serve a blank page that asks for the client hints, and echo a request's headers back."""

    def do_GET(self) -> None:
        headers = {k.lower(): v for k, v in self.headers.items()}
        echo = self.path.startswith(_ECHO_PATH)
        body = json.dumps(headers).encode() if echo else b"<html><body></body></html>"
        self.send_response(200)
        self.send_header("Accept-CH", _CLIENT_HINTS)
        self.send_header("Content-Type", "application/json" if echo else "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: Any) -> None:
        return


@pytest.fixture
def echo_origin() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


async def test_every_fortress_context_presents_one_identity_whose_page_matches_its_headers(
    echo_origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not browser_host_settings.BROWSER_HOST_FORTRESS:
        pytest.fail("this tier runs Fortress: set BROWSER_HOST_FORTRESS=true and CHROMIUM_BIN")
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
    host = BrowserHost(on_fatal=lambda: None)
    await host.start()
    seen: list[dict[str, Any]] = []
    try:
        for _ in range(_CONTEXTS):
            seen.append(await _read_identity(await host.create_context(None), echo_origin))
    finally:
        await host.stop()

    page = seen[0]["page"]
    # browser-use's defaults delete the speech API, which a Windows Chrome and the pinned voices need.
    assert page["speech"] == "object"
    headers = {name: seen[0]["headers"].get(name) for name in _IDENTITY_HEADERS}
    for other in seen[1:]:
        assert other["page"] == page
        assert {name: other["headers"].get(name) for name in _IDENTITY_HEADERS} == headers
    assert headers["user-agent"] == page["ua"]
    assert headers["accept-language"].split(",")[0] == page["languages"][0]
    assert json.loads(headers["sec-ch-ua-platform"]) == page["he"]["platform"]
    assert json.loads(headers["sec-ch-ua-platform-version"]) == page["he"]["platformVersion"]
    assert json.loads(headers["sec-ch-ua-arch"]) == page["he"]["architecture"]
