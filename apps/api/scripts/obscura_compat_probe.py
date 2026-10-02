"""Find where Obscura renders a site differently from Chrome, as named JS errors.

Loads each site in a fresh Obscura and a fresh headless Chrome, both driven
over CDP, and compares what a page is made of once it has settled: the
JavaScript errors each engine threw, and a fingerprint of what a person could
use (text inputs, buttons, links, visible text). A site where Obscura throws an
error Chrome does not, or shows far less to use, has a gap. When the server
answered the two engines with the same main document, the gap is the engine's:
it renders differently, and the error names the spot to patch in
crates/obscura-js/js/bootstrap.js. When the server sent Obscura a different
document (a bot wall, a challenge), the gap is the server's decision, reported
on its own and never a failure.

    uv run --group backend python scripts/obscura_compat_probe.py [--baseline FILE] [url ...]

With no URLs it probes COMMON_SITES. Needs OBSCURA_BIN and CHROMIUM_BIN (or
/opt/google/chrome/chrome). Exits 1 when any site renders differently; with
--baseline, only when a site outside that file does.
"""

import argparse
import asyncio
import base64
import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit

import httpx
import websockets

#: The checkout this script lives in (apps/api/scripts/ -> the repo root).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Sites people commonly send a browser task to, one per shape of page:
#: search, forms, docs, news, shopping, travel, SPAs built on the big frameworks.
COMMON_SITES = [
    "https://duckduckgo.com/",
    "https://duckduckgo.com/?q=attention+is+all+you+need&ia=web",
    "https://www.bing.com/",
    "https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)",
    "https://news.ycombinator.com/",
    "https://github.com/h4ckf0r0day/obscura",
    "https://www.reddit.com/r/programming/",
    "https://stackoverflow.com/questions",
    "https://www.selenium.dev/selenium/web/web-form.html",
    "https://www.amazon.com/",
    "https://www.ebay.com/",
    "https://www.booking.com/",
    "https://www.airbnb.com/",
    "https://www.google.com/travel/flights",
    "https://www.nytimes.com/",
    "https://www.bbc.com/news",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
    "https://docs.python.org/3/library/asyncio.html",
    "https://www.npmjs.com/package/react",
    "https://vercel.com/",
    "https://nextjs.org/",
    "https://react.dev/",
    "https://www.youtube.com/",
]

OBSCURA_PORT = 39333
CHROME_PORT = 39334
SETTLE_SECONDS = 6.0
NAVIGATE_TIMEOUT_SECONDS = 90.0
#: A wedged engine answers no CDP call at all; past this a site is a failed load.
SITE_TIMEOUT_SECONDS = 180.0
#: Obscura showing under this share of Chrome's inputs, buttons or links is a gap.
MIN_SHARE_OF_CHROME = 0.5
#: Main-document bodies further apart than this are different documents. Measured
#: 2026-10-02: one site's page across loads and engines, up to 3.4x (bing, reddit);
#: a bot wall vs the real page, 14x (16 KB challenge vs 226 KB) to 150x (amazon).
MAX_SAME_DOCUMENT_SIZE_RATIO = 10.0

_FINGERPRINT_JS = """(() => {
  const shown = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const count = (sel) => [...document.querySelectorAll(sel)].filter(shown).length;
  return {
    title: document.title,
    ready: document.readyState,
    inputs: count('input:not([type=hidden]), textarea, select, [contenteditable=""], [contenteditable=true]'),
    buttons: count('button, [role=button], input[type=submit]'),
    links: count('a[href]'),
    text: (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').length,
  };
})()"""


@dataclass
class Document:
    """The server's answer to the main frame's last navigation, at the URL it landed on."""

    status: int
    url: str
    #: Decoded body bytes; None when the engine no longer holds the body.
    size: int | None

    def __str__(self) -> str:
        size = "? KB" if self.size is None else f"{self.size / 1024:.1f} KB"
        return f"{self.status} {size} {self.url[:100]}"


@dataclass
class PageReport:
    """What one engine made of one site."""

    fingerprint: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    document: Document | None = None
    failure: str | None = None


class CdpBrowser:
    """One CDP connection to a browser's root endpoint, one context per page load."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._ws: Any = None
        self._next_id = 0

    async def __aenter__(self) -> "CdpBrowser":
        async with httpx.AsyncClient() as http:
            version = await http.get(f"http://127.0.0.1:{self.port}/json/version", timeout=10)
        # No keepalive pings: an engine busy laying out a page answers nothing for
        # a while, and a ping timeout would drop the connection mid-load.
        self._ws = await websockets.connect(
            version.json()["webSocketDebuggerUrl"], max_size=None, ping_interval=None
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._ws.close()

    async def _call(
        self,
        method: str,
        events: list[dict[str, Any]],
        session: str | None = None,
        **params: object,
    ) -> dict[str, Any]:
        self._next_id += 1
        message: dict[str, Any] = {"id": self._next_id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        await self._ws.send(json.dumps(message))
        while True:
            reply = json.loads(await self._ws.recv())
            if reply.get("id") == self._next_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error'].get('message')}")
                return dict(reply.get("result") or {})
            if "method" in reply:
                events.append(reply)

    async def _drain(self, seconds: float, events: list[dict[str, Any]]) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while (left := end - loop.time()) > 0:
            try:
                reply = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=left))
            except TimeoutError:
                return
            if "method" in reply:
                events.append(reply)

    async def load(self, url: str) -> PageReport:
        events: list[dict[str, Any]] = []
        report = PageReport()
        context = (await self._call("Target.createBrowserContext", events))["browserContextId"]
        try:
            target = await self._call(
                "Target.createTarget", events, url="about:blank", browserContextId=context
            )
            session = (
                await self._call(
                    "Target.attachToTarget", events, targetId=target["targetId"], flatten=True
                )
            )["sessionId"]
            await self._call("Page.enable", events, session)
            await self._call("Runtime.enable", events, session)
            await self._call("Network.enable", events, session)
            await asyncio.wait_for(
                self._call("Page.navigate", events, session, url=url), NAVIGATE_TIMEOUT_SECONDS
            )
            await self._drain(SETTLE_SECONDS, events)
            result = await self._call(
                "Runtime.evaluate", events, session, expression=_FINGERPRINT_JS, returnByValue=True
            )
            report.fingerprint = dict((result.get("result") or {}).get("value") or {})
            report.document = await self._main_document(events, session)
        except Exception as exc:
            report.failure = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            # Bounded: this also runs when the site deadline cancels a wedged load.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._call("Target.disposeBrowserContext", events, browserContextId=context),
                    10,
                )
        report.errors = _errors(events)
        return report

    async def _main_document(self, events: list[dict[str, Any]], session: str) -> Document | None:
        """The main frame's last committed document, sized from its body as the engine decoded it.

        Not loadingFinished's encodedDataLength: Chrome counts compressed bytes
        plus headers there and Obscura the decoded body, so they never compare.
        """
        frame, response = _main_response(events)
        if response is None:
            return None
        try:
            body = await self._call(
                "Network.getResponseBody", events, session, requestId=response["requestId"]
            )
            raw = str(body.get("body") or "")
            size: int | None = (
                len(base64.b64decode(raw)) if body.get("base64Encoded") else len(raw.encode())
            )
        except RuntimeError:
            size = None
        status = int((response.get("response") or {}).get("status") or 0)
        return Document(status, str(frame.get("url") or ""), size)


def _main_response(events: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The main frame as it last committed, and the Network.responseReceived behind it.

    The URL to compare is the frame's: Obscura's responseReceived carries the
    URL before redirects (airbnb's 302 handoff), the frame the one it landed on.
    Only a loader's first frameNavigated is its commit; Obscura re-sends one for
    a same-document URL change (wikipedia's replaceState), where Chrome sends
    navigatedWithinDocument.
    """
    frame: dict[str, Any] = {}
    for event in events:
        committed = (event.get("params") or {}).get("frame") or {}
        if (
            event.get("method") == "Page.frameNavigated"
            and not committed.get("parentId")
            and committed.get("loaderId") != frame.get("loaderId")
        ):
            frame = committed
    found = None
    for event in events:
        params = event.get("params") or {}
        if (
            event.get("method") == "Network.responseReceived"
            and params.get("type") == "Document"
            and params.get("loaderId") == frame.get("loaderId")
        ):
            found = params
    return frame, found


def _errors(events: list[dict[str, Any]]) -> list[str]:
    """Distinct uncaught exceptions and console errors, first line each."""
    found: list[str] = []
    for event in events:
        params = event.get("params") or {}
        if event.get("method") == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails") or {}
            text = (details.get("exception") or {}).get("description") or details.get("text", "")
        elif event.get("method") == "Runtime.consoleAPICalled" and params.get("type") == "error":
            text = " ".join(
                str(a.get("value") or a.get("description") or "") for a in params.get("args", [])
            )
        else:
            continue
        line = text.strip().splitlines()[0][:220] if text.strip() else ""
        if line and line not in found:
            found.append(line)
    return found


def _gaps(obscura: PageReport, chrome: PageReport) -> list[str]:
    """What Obscura got wrong on this site, relative to what Chrome did with it."""
    if obscura.failure:
        return [f"load failed: {obscura.failure}"]
    gaps = [f"error only in Obscura: {e}" for e in obscura.errors if e not in chrome.errors]
    for key in ("inputs", "buttons", "links"):
        seen, expected = obscura.fingerprint.get(key, 0), chrome.fingerprint.get(key, 0)
        if expected >= 2 and seen < expected * MIN_SHARE_OF_CHROME:
            gaps.append(f"{key}: {seen} shown vs {expected} in Chrome")
    return gaps


def _different_document(obscura: Document | None, chrome: Document | None) -> str | None:
    """How the server's answer to Obscura differs from its answer to Chrome; None if it doesn't.

    Without both documents nothing shows the server chose differently, so the
    gap stays the engine's.
    """
    if obscura is None or chrome is None:
        return None
    if obscura.status // 100 != chrome.status // 100:
        return f"status {obscura.status} vs {chrome.status} in Chrome"
    seen, expected = urlsplit(obscura.url), urlsplit(chrome.url)
    if (seen.hostname, seen.path) != (expected.hostname, expected.path):
        return f"ended at {obscura.url[:100]} vs {chrome.url[:100]} in Chrome"
    if obscura.size is not None and chrome.size is not None:
        ratio = max(obscura.size, chrome.size) / max(min(obscura.size, chrome.size), 1)
        if ratio > MAX_SAME_DOCUMENT_SIZE_RATIO:
            return (
                f"body {obscura.size / 1024:.1f} KB vs {chrome.size / 1024:.1f} KB "
                f"in Chrome, {ratio:.0f}x apart"
            )
    return None


async def _start(argv: list[str], env: dict[str, str] | None = None) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *argv, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )


async def _await_endpoint(port: int) -> None:
    async with httpx.AsyncClient() as http:
        for _ in range(100):
            try:
                (
                    await http.get(f"http://127.0.0.1:{port}/json/version", timeout=1)
                ).raise_for_status()
                return
            except httpx.HTTPError:
                await asyncio.sleep(0.2)
    raise RuntimeError(f"no CDP endpoint on port {port}")


async def _load(port: int, url: str) -> PageReport:
    """Load one site over a connection of its own, so a hang on one site ends only that site."""
    try:
        async with CdpBrowser(port) as browser:
            return await asyncio.wait_for(browser.load(url), SITE_TIMEOUT_SECONDS)
    except TimeoutError:
        return PageReport(failure=f"no answer within {SITE_TIMEOUT_SECONDS:.0f}s")
    except Exception as exc:
        return PageReport(failure=f"{type(exc).__name__}: {exc}"[:200])


async def _start_obscura(obscura_bin: str) -> asyncio.subprocess.Process:
    return await _start(
        [obscura_bin, "serve", "--port", str(OBSCURA_PORT), "--stealth"],
        env={
            **os.environ,
            "OBSCURA_SCRIPT_DEADLINE_MS": "60000",
            # The default keeps the last 128 bodies, so on a page of many
            # subresources the main document's is gone before it is sized.
            "OBSCURA_NETWORK_BODY_BUFFER_ENTRIES": "10000",
        },
    )


@dataclass
class ProbeResult:
    """Sites whose gap the engine owns, and sites the server sent Obscura something else."""

    rendered_differently: set[str] = field(default_factory=set)
    #: URL -> how the two main documents differ.
    served_different_document: dict[str, str] = field(default_factory=dict)


async def _running_obscura(
    obscura: asyncio.subprocess.Process, obscura_bin: str
) -> asyncio.subprocess.Process:
    """Return the engine to probe the next site in, restarted when the last site crashed it.

    A crash is itself a gap on the site that caused it; the next site still gets an engine.
    """
    if obscura.returncode is None:
        return obscura
    restarted = await _start_obscura(obscura_bin)
    await _await_endpoint(OBSCURA_PORT)
    return restarted


async def _stop_wedged(obscura: asyncio.subprocess.Process) -> None:
    """Kill an engine that failed a site while still running: wedged, it would fail every later site too."""
    if obscura.returncode is None:
        obscura.kill()
        await obscura.wait()


def _report_site(result: ProbeResult, url: str, o: PageReport, c: PageReport) -> None:
    """Sort one site's gap by its owner into result, and print what differs."""
    gaps = _gaps(o, c)
    different = _different_document(o.document, c.document) if gaps else None
    if different:
        result.served_different_document[url] = different
        status = "DOC "
    elif gaps:
        result.rendered_differently.add(url)
        status = "GAP "
    else:
        status = "ok  "
    print(
        f"{status}{url}  obscura inputs={o.fingerprint.get('inputs')} "
        f"buttons={o.fingerprint.get('buttons')} links={o.fingerprint.get('links')} | "
        f"chrome inputs={c.fingerprint.get('inputs')} "
        f"buttons={c.fingerprint.get('buttons')} links={c.fingerprint.get('links')}",
        flush=True,
    )
    print(f"      document: obscura {o.document} | chrome {c.document}", flush=True)
    if different:
        print(f"      served a different document: {different}", flush=True)
    for gap in gaps:
        print(f"      {gap}", flush=True)


async def probe(urls: list[str], obscura_bin: str, chrome_bin: str) -> ProbeResult:
    """Probe each site in both engines, print what differs, and sort each gap by its owner."""
    profile = tempfile.mkdtemp(prefix="compat-chrome-")
    obscura = await _start_obscura(obscura_bin)
    chrome = await _start(
        [
            chrome_bin,
            "--headless=new",
            f"--remote-debugging-port={CHROME_PORT}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    )
    result = ProbeResult()
    try:
        await asyncio.gather(_await_endpoint(OBSCURA_PORT), _await_endpoint(CHROME_PORT))
        for url in urls:
            obscura = await _running_obscura(obscura, obscura_bin)
            o, c = await asyncio.gather(_load(OBSCURA_PORT, url), _load(CHROME_PORT, url))
            if o.failure:
                await _stop_wedged(obscura)
            _report_site(result, url, o, c)
    finally:
        for process in (obscura, chrome):
            if process.returncode is None:
                process.terminate()
        await asyncio.gather(obscura.wait(), chrome.wait())
        shutil.rmtree(profile, ignore_errors=True)
    return result


def _read_baseline(path: Path) -> set[str]:
    """URLs of sites with known gaps: one per line, lines starting with # ignored.

    The file must sit inside this repository; the baseline is a checked-in ratchet.
    """
    resolved = path.resolve()
    if not resolved.is_relative_to(REPO_ROOT):
        sys.exit(f"--baseline must be a file in this repository, not {path}")
    lines = (line.strip() for line in resolved.read_text().splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def _list(heading: str, urls: list[str]) -> None:
    print(heading + (":" if urls else ""))
    for url in urls:
        print(f"      {url}")


def _verdict(urls: list[str], result: ProbeResult, baseline: set[str] | None) -> int:
    """Print the summary and return the exit code; only rendering gaps can fail the run.

    A baseline excuses only its own sites. A baseline site served a different
    document was not compared this run, so it is neither a gap nor removable.
    """
    gapped, served = result.rendered_differently, result.served_different_document
    print(f"\n{len(gapped)} of {len(urls)} sites render differently in Obscura")
    _list(
        f"{len(served)} sites served Obscura a different document than Chrome "
        "(the server's decision, not an engine gap; never fails the run)",
        [f"{url}  {served[url]}" for url in urls if url in served],
    )
    if baseline is None:
        return 1 if gapped else 0
    new = [url for url in urls if url in gapped and url not in baseline]
    known = [url for url in urls if url in gapped and url in baseline]
    removable = [url for url in urls if url in baseline and url not in gapped | served.keys()]
    print(f"{len(known)} known rendering gaps, listed in the baseline")
    _list(
        f"{len(removable)} baseline sites now match Chrome; remove them from the baseline",
        removable,
    )
    _list(f"{len(new)} new rendering gaps at sites not in the baseline", new)
    print("FAIL: new rendering gaps" if new else "PASS: no rendering gaps outside the baseline")
    return 1 if new else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="*", default=COMMON_SITES)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="file of sites with known rendering gaps, one URL per line; only others fail the run",
    )
    args = parser.parse_args()
    baseline = _read_baseline(args.baseline) if args.baseline else None
    obscura_bin = os.environ.get("OBSCURA_BIN") or ""
    chrome_bin = os.environ.get("CHROMIUM_BIN") or "/opt/google/chrome/chrome"
    if not Path(obscura_bin).is_file():
        sys.exit("set OBSCURA_BIN to the obscura binary")
    result = asyncio.run(probe(args.urls, obscura_bin, chrome_bin))
    sys.exit(_verdict(args.urls, result, baseline))


if __name__ == "__main__":
    main()
