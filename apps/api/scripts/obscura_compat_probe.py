"""Find where Obscura renders a site differently from Chrome, as named JS errors.

Loads each site in a fresh Obscura and a fresh headless Chrome, both driven
over CDP, and compares what a page is made of once it has settled: the
JavaScript errors each engine threw, and a fingerprint of what a person could
use (text inputs, buttons, links, visible text). A site where Obscura throws an
error Chrome does not, or shows far less to use, is an engine gap; the error
names the spot to patch in crates/obscura-js/js/bootstrap.js.

    uv run --group backend python scripts/obscura_compat_probe.py [--baseline FILE] [url ...]

With no URLs it probes COMMON_SITES. Needs OBSCURA_BIN and CHROMIUM_BIN (or
/opt/google/chrome/chrome). Exits 1 when any site has a gap; with --baseline,
only when a site outside that file has one.
"""

import argparse
import asyncio
import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

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
    "https://the-internet.herokuapp.com/dynamic_loading/2",
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
class PageReport:
    """What one engine made of one site."""

    fingerprint: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
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
            await asyncio.wait_for(
                self._call("Page.navigate", events, session, url=url), NAVIGATE_TIMEOUT_SECONDS
            )
            await self._drain(SETTLE_SECONDS, events)
            result = await self._call(
                "Runtime.evaluate", events, session, expression=_FINGERPRINT_JS, returnByValue=True
            )
            report.fingerprint = dict((result.get("result") or {}).get("value") or {})
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
            "OBSCURA_NAV_TIMEOUT_MS": "90000",
            "OBSCURA_SCRIPT_DEADLINE_MS": "60000",
        },
    )


async def probe(urls: list[str], obscura_bin: str, chrome_bin: str) -> set[str]:
    """Probe each site in both engines, print what differs, and return the sites with a gap."""
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
    gapped: set[str] = set()
    try:
        await asyncio.gather(_await_endpoint(OBSCURA_PORT), _await_endpoint(CHROME_PORT))
        for url in urls:
            if obscura.returncode is not None:
                # A crash is itself a gap on the site that caused it; the next
                # site still gets an engine to run in.
                obscura = await _start_obscura(obscura_bin)
                await _await_endpoint(OBSCURA_PORT)
            o, c = await asyncio.gather(_load(OBSCURA_PORT, url), _load(CHROME_PORT, url))
            if o.failure and obscura.returncode is None:
                # A wedged engine would fail every later site too.
                obscura.kill()
                await obscura.wait()
            gaps = _gaps(o, c)
            if gaps:
                gapped.add(url)
            status = "GAP " if gaps else "ok  "
            print(
                f"{status}{url}  obscura inputs={o.fingerprint.get('inputs')} "
                f"buttons={o.fingerprint.get('buttons')} links={o.fingerprint.get('links')} | "
                f"chrome inputs={c.fingerprint.get('inputs')} "
                f"buttons={c.fingerprint.get('buttons')} links={c.fingerprint.get('links')}",
                flush=True,
            )
            for gap in gaps:
                print(f"      {gap}", flush=True)
    finally:
        for process in (obscura, chrome):
            if process.returncode is None:
                process.terminate()
        await asyncio.gather(obscura.wait(), chrome.wait())
        shutil.rmtree(profile, ignore_errors=True)
    return gapped


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


def _verdict(urls: list[str], gapped: set[str], baseline: set[str] | None) -> int:
    """Print the summary and return the exit code; a baseline only excuses its own sites."""
    print(f"\n{len(gapped)} of {len(urls)} sites differ in Obscura")
    if baseline is None:
        return 1 if gapped else 0
    new = [url for url in urls if url in gapped and url not in baseline]
    known = [url for url in urls if url in gapped and url in baseline]
    removable = [url for url in urls if url in baseline and url not in gapped]
    print(f"{len(known)} known, listed in the baseline")
    _list(
        f"{len(removable)} baseline sites now match Chrome; remove them from the baseline",
        removable,
    )
    _list(f"{len(new)} new gaps at sites not in the baseline", new)
    print("FAIL: new gaps" if new else "PASS: no gaps outside the baseline")
    return 1 if new else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="*", default=COMMON_SITES)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="file of sites with known gaps, one URL per line; only other sites fail the run",
    )
    args = parser.parse_args()
    baseline = _read_baseline(args.baseline) if args.baseline else None
    obscura_bin = os.environ.get("OBSCURA_BIN") or ""
    chrome_bin = os.environ.get("CHROMIUM_BIN") or "/opt/google/chrome/chrome"
    if not Path(obscura_bin).is_file():
        sys.exit("set OBSCURA_BIN to the obscura binary")
    gapped = asyncio.run(probe(args.urls, obscura_bin, chrome_bin))
    sys.exit(_verdict(args.urls, gapped, baseline))


if __name__ == "__main__":
    main()
