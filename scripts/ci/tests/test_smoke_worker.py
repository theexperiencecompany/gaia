"""smoke-worker.sh: a route passes only when it rendered, and the worker dies with the script.

A 200 is not a render: Next's error page can come back 200, and a page whose
title is missing is not the page that was asked for. The booted worker is
pnpm -> wrangler -> workerd, and killing only the first of them left workerd
holding the port for the next run. The real script runs in a copy of its tree
with wrangler, pnpm and curl stubbed; the stub wrangler forks a listener that
stands in for workerd.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess

import pytest

SCRIPT = Path(__file__).parent.parent / "smoke-worker.sh"

WRANGLER_STUB = """\
#!/usr/bin/env bash
set -euo pipefail
port="$3"
python3 -c '
import socket, sys, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen()
time.sleep(600)
' "$port" &
echo "$!" > "$FAKE_STATE/workerd.pid"
echo "Ready on http://127.0.0.1:$port"
wait
"""

PNPM_STUB = """\
#!/usr/bin/env bash
[ "$1 $2" = "exec playwright" ] || { echo "unexpected pnpm $*" >&2; exit 2; }
echo "$SMOKE_BASE_URL" > "$FAKE_STATE/playwright.url"
exit "${FAKE_PLAYWRIGHT_EXIT:-0}"
"""

CURL_STUB = """\
#!/usr/bin/env bash
set -euo pipefail
out=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w|--max-time) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
response="$FAKE_RESPONSES/$(printf '%s' "${url#http://127.0.0.1:*/}" | tr '/' '_')"
if [ ! -f "$response" ]; then printf '404'; exit 0; fi
tail -n +2 "$response" > "$out"
head -n 1 "$response" | tr -d '\\n'
"""

ROUTE = "/login"
TITLE = "Login | GAIA"
RENDERED = f"<html><head><title>{TITLE}</title></head><body>ok</body></html>"


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def _listening(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Smoke:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.responses = root / "responses"
        self.port = _free_port()

    def respond(self, route: str, code: int, body: str) -> None:
        (self.responses / route.lstrip("/").replace("/", "_")).write_text(f"{code}\n{body}\n")

    def run(self, *, playwright_exit: int = 0) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "FAKE_STATE": str(self.state),
            "FAKE_RESPONSES": str(self.responses),
            "FAKE_PLAYWRIGHT_EXIT": str(playwright_exit),
            "SMOKE_PORT": str(self.port),
            "SMOKE_ROUTES": f"{ROUTE} {TITLE}",
        }
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "ci" / "smoke-worker.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def workerd_pid(self) -> int:
        return int((self.state / "workerd.pid").read_text())


@pytest.fixture
def smoke(tmp_path: Path) -> Iterator[Smoke]:
    (tmp_path / "scripts" / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "scripts" / "ci" / "smoke-worker.sh")
    (tmp_path / "apps" / "web" / ".open-next").mkdir(parents=True)
    (tmp_path / "apps" / "web" / ".open-next" / "worker.js").write_text("")
    (tmp_path / "apps" / "web" / "node_modules" / ".bin").mkdir(parents=True)
    _executable(tmp_path / "apps" / "web" / "node_modules" / ".bin" / "wrangler", WRANGLER_STUB)
    (tmp_path / "bin").mkdir()
    _executable(tmp_path / "bin" / "pnpm", PNPM_STUB)
    _executable(tmp_path / "bin" / "curl", CURL_STUB)
    (tmp_path / "state").mkdir()
    (tmp_path / "responses").mkdir()
    harness = Smoke(tmp_path)
    yield harness
    pid_file = harness.state / "workerd.pid"
    if pid_file.exists() and _alive(harness.workerd_pid()):
        os.kill(harness.workerd_pid(), signal.SIGKILL)


def test_a_rendered_route_passes_and_the_browser_check_runs_on_the_booted_worker(
    smoke: Smoke,
) -> None:
    smoke.respond(ROUTE, 200, RENDERED)

    result = smoke.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert (smoke.state / "playwright.url").read_text().strip() == f"http://127.0.0.1:{smoke.port}"


def test_a_200_without_the_route_title_fails(smoke: Smoke) -> None:
    smoke.respond(ROUTE, 200, "<html><head><title>GAIA</title></head></html>")

    result = smoke.run()

    assert result.returncode != 0
    assert f"{ROUTE} rendered without <title>{TITLE}</title>" in result.stdout


def test_a_200_next_error_page_fails(smoke: Smoke) -> None:
    smoke.respond(ROUTE, 200, f'<html id="__next_error__"><title>{TITLE}</title></html>')

    result = smoke.run()

    assert result.returncode != 0
    assert f"{ROUTE} rendered the Next error page" in result.stdout


def test_a_non_200_fails(smoke: Smoke) -> None:
    smoke.respond(ROUTE, 500, RENDERED)

    result = smoke.run()

    assert result.returncode != 0
    assert f"{ROUTE} returned 500" in result.stdout


def test_a_failed_browser_check_fails(smoke: Smoke) -> None:
    smoke.respond(ROUTE, 200, RENDERED)

    result = smoke.run(playwright_exit=1)

    assert result.returncode != 0
    assert "the browser check failed" in result.stdout


def test_the_worker_and_its_children_stop_with_the_script(smoke: Smoke) -> None:
    smoke.respond(ROUTE, 200, RENDERED)

    smoke.run()

    assert not _alive(smoke.workerd_pid())
    assert not _listening(smoke.port)
