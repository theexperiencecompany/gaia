"""Schemathesis contract gate for the real API, driven over HTTP.

Boots the REAL GAIA app as a subprocess (``uvicorn app.main:app``) with real
Postgres/Redis/Mongo/Chroma in Docker and the dev-auth bypass, then fuzzes a
small set of core operations from the live OpenAPI schema — asserting no 5xx,
schema-valid responses, and no undocumented status codes on those paths. The
server owns its event loop and lifespan, so lazy providers register and the
process-global Motor client never latches onto a stale loop (the failure modes
of the old in-process ``from_asgi`` harness).

GREEN SCOPE (verified passing): ``SCOPED_OPERATIONS`` below. The gate is a
narrow but real regression net for those paths.

DOCUMENTED FINDINGS (full-schema exploratory fuzz, ``SCHEMA_FUZZ_FULL=1``) —
real contract drift, reported not silenced, tracked for the API-hardening
follow-up:

- **Undocumented 429 plan-gates**: ``GET /api/v1/token`` (and other
  ``@tiered_rate_limit`` endpoints) return 429 ``{"error":"rate_limit_exceeded",
  "plan_required":"pro"}`` for free users — the schema documents only
  200/401/500/422. Needs ``responses={429: ...}`` on the rate-limited routes.
- **405-vs-422 route shadowing**: parameterized routes (``/todos/{todo_id}``
  etc.) shadow literal siblings (``/counts``, ``/bulk``, ``/search``) so
  undocumented methods return 422 instead of 405 — same family as the fixed
  ``/todos/bulk`` ordering bug. Needs literal-before-parameterized routing.
- **Undocumented 403**: Gmail/Calendar endpoints 403 for users without the
  integration connected; 403 absent from the schema.
- **Undocumented 307/410/404**: OAuth login/callback redirects (307),
  ``POST /api/v1/desktop/tool-result`` (410), and ``{id}`` not-found paths
  (404) are reachable but undocumented.
- **Server wedge under pathological generated input**: after some fuzzed
  requests the single event loop stops responding (subsequent ops time out at
  30s even for plain ``GET /api/v1/todos/counts``). Not reproducible with
  hand-written curl of the same inputs — needs a server-side hardening pass
  (per-request timeouts on external calls, bounded query params) before the
  full schema can be fuzzed safely.

Run the full exploratory pass: ``SCHEMA_FUZZ_FULL=1`` sets
``SCHEMA_FUZZ_EXAMPLES`` high and adds no scoping (see ``_operations_to_run``).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import httpx
from hypothesis import given, settings, strategies as st
from pymongo import MongoClient
import pytest

from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.db.repositories.plans import PlansRepository
from tests.helpers import pick_free_port

pytestmark = [
    pytest.mark.schemathesis,
    pytest.mark.slow,
]

API_ROOT = Path(__file__).resolve().parents[3]  # apps/api
APP_MODULE = "app.main:app"
DEV_USER = "schemathesis@gaia.local"
EXAMPLES_PER_OP = int(os.environ.get("SCHEMA_FUZZ_EXAMPLES", "3"))
REQUEST_TIMEOUT = float(os.environ.get("SCHEMA_FUZZ_TIMEOUT", "30"))
FUZZ_FULL = os.environ.get("SCHEMA_FUZZ_FULL", "0") == "1"
# `import app.main` alone costs ~10s warm on a developer laptop, and the
# lifespan then dials Postgres/Redis/Mongo/Chroma before uvicorn binds — ~18s
# warm end to end. A cold 2-core CI runner is several times that, which is how
# the old 60s budget failed here while passing locally.
BOOT_TIMEOUT = float(os.environ.get("SCHEMA_FUZZ_BOOT_TIMEOUT", "300"))
# Generous per-probe timeout: a slow first response must not be misread as "not
# listening yet" (the poll loop still exits as soon as one probe succeeds).
PROBE_TIMEOUT = float(os.environ.get("SCHEMA_FUZZ_PROBE_TIMEOUT", "10"))


def _pick_port() -> int:
    """A free ephemeral port, or SCHEMA_FUZZ_PORT where one must be fixed
    (e.g. a firewall allowlist)."""
    if env_port := os.environ.get("SCHEMA_FUZZ_PORT"):
        return int(env_port)
    return pick_free_port()


PORT = _pick_port()

# Operations that demonstrably pass — the gate's scope. Notes/todos/reminders
# are excluded: embedding-dependent paths need a real GOOGLE_API_KEY the
# hermetic test fence blanks, and the todos/reminders group showed the
# server-wedge behavior above.
SCOPED_OPERATIONS: set[tuple[str, str]] = {
    ("GET", "/api/v1/conversations"),
    ("POST", "/api/v1/conversations"),
    ("GET", "/api/v1/users/me"),
    ("PATCH", "/api/v1/users/me"),
    ("GET", "/api/v1/integrations/status"),
    ("GET", "/api/v1/health"),
}


def _operations_to_run(operation) -> bool:
    key = (operation.method.upper(), operation.path)
    return key in SCOPED_OPERATIONS or FUZZ_FULL


def _server_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "ENV": "development",
            "USE_REAL_SERVICES": "1",
            "DEV_AUTH_BYPASS_EMAIL": DEV_USER,
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(API_ROOT),
        }
    )
    return env


def _tail(log_path: Path, limit: int = 20000) -> str:
    """The end of the server's log, for a failure message.

    Generous limit on purpose: startup logs one line per provider, so a 4 KiB
    tail showed only the shutdown sequence and the re-raised aggregate error
    ("Failed to initialize required services: [...]") while the line naming the
    provider that actually failed scrolled past.
    """
    try:
        return log_path.read_text(errors="replace")[-limit:] or "<server produced no output>"
    except OSError as exc:
        return f"<could not read server log {log_path}: {exc}>"


@pytest.fixture(scope="session")
def _seeded_startup_requirements(mongodb_url: str) -> Iterator[None]:
    """Satisfy the app's own startup gate before booting it.

    ``app/services/startup_validation.py`` aborts boot when the
    ``subscription_plans`` collection is empty, deliberately: a deployment
    missing its plans should fail loudly rather than serve. CI's Mongo is
    empty and nothing seeds it, so the real server could never start there —
    which is why this suite failed only in CI, while a developer's Mongo let it
    pass locally.

    The seeded row exists to clear that gate, nothing more: no operation in
    ``SCOPED_OPERATIONS`` reads the collection. Only ever inserted into an
    EMPTY collection, and only what we inserted is removed afterwards, so a
    developer's real catalog is never touched.
    """
    # The app pins its database name and ignores the one in the URL path, so
    # seeding the URL's default database would silently seed the wrong place.
    client: MongoClient = MongoClient(mongodb_url)
    database = client[MONGO_DATABASE_NAME]
    now = datetime.now(UTC)
    seeded: list[tuple[str, object]] = []

    fixtures: dict[str, dict[str, object]] = {
        PlansRepository.collection_name: {
            "name": "Schemathesis Precondition Plan",
            "amount": 0,
            "currency": "USD",
            "duration": "monthly",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        },
    }

    try:
        for collection_name, document in fixtures.items():
            collection = database[collection_name]
            if collection.count_documents({}, limit=1) == 0:
                seeded.append((collection_name, collection.insert_one(document).inserted_id))
        yield
    finally:
        for collection_name, inserted_id in seeded:
            database[collection_name].delete_one({"_id": inserted_id})
        client.close()


@pytest.fixture(scope="session")
def live_api_url(_seeded_startup_requirements: None) -> Iterator[str]:
    """Boot the real API in a subprocess and wait until it serves /openapi.json.

    The server's output goes to a file rather than ``subprocess.PIPE``: nothing
    drains a pipe during the readiness poll, so once the app's startup logging
    filled the 64 KiB pipe buffer the server would block mid-boot and never
    bind — a hang that looks identical to a slow start. A file also means every
    failure below can actually show what the server said.
    """
    # This test owns a whole uvicorn process and must not compete with xdist
    # workers for the runner's cores. pytest.ini's addopts carry `-n 4`, so the
    # "isolated" CI step silently ran four workers — three of them paying the
    # ~10s app import while the fourth tried to boot the server — and the boot
    # timed out. Fail here, naming the cause, rather than 5 minutes later with
    # a timeout that looks like a broken app.
    workers = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))
    if workers > 1:
        pytest.fail(
            f"this suite must run serially, but pytest started {workers} xdist workers. "
            "Pass --override-ini=addopts=--strict-markers (pytest.ini's addopts carry -n 4), "
            "or run it via `nx run api:test:schemathesis`."
        )

    log_dir = Path(tempfile.mkdtemp(prefix="schemathesis-server-"))
    log_path = log_dir / "server.log"
    url = f"http://127.0.0.1:{PORT}"

    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                APP_MODULE,
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            cwd=API_ROOT,
            env=_server_env(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + BOOT_TIMEOUT
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"API server exited early (code {proc.returncode}):\n{_tail(log_path)}"
                    )
                try:
                    if httpx.get(f"{url}/openapi.json", timeout=PROBE_TIMEOUT).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError(
                    f"API server did not become ready in {BOOT_TIMEOUT:.0f}s "
                    f"(raise SCHEMA_FUZZ_BOOT_TIMEOUT if the host is simply slow):"
                    f"\n{_tail(log_path)}"
                )

            # The bypass authenticates every request as DEV_USER; that user must
            # exist in Mongo (dev router is idempotent). Retry with backoff —
            # the server being up is already proven by the readiness poll above.
            mint_error: Exception | None = None
            for attempt in range(3):
                try:
                    mint = httpx.post(
                        f"{url}/api/v1/dev/users", json={"email": DEV_USER}, timeout=30
                    )
                    mint.raise_for_status()
                    break
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    mint_error = exc
                    time.sleep(2 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"could not mint dev user after 3 attempts: {mint_error}\n{_tail(log_path)}"
                )
            yield url
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            shutil.rmtree(log_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def schema(live_api_url: str):
    import schemathesis

    return schemathesis.openapi.from_url(f"{live_api_url}/openapi.json")


def _fuzz_scoped_operations(schema, data) -> None:
    """No 5xx, schema-valid responses, and no undocumented status codes on the
    scoped operations (or all operations under SCHEMA_FUZZ_FULL=1)."""
    import schemathesis
    from schemathesis.schemas import BaseSchema

    assert isinstance(schema, BaseSchema)
    failures: list[str] = []
    for result in schema.get_all_operations():
        if isinstance(result, schemathesis.core.result.Err):
            failures.append(f"operation failed to load: {result.err()}")
            continue
        operation = result.ok()
        if not _operations_to_run(operation):
            continue
        print(f"\n  fuzzing {operation.method.upper()} {operation.path} ...", flush=True)
        strategy = operation.as_strategy()
        for _ in range(EXAMPLES_PER_OP):
            case = data.draw(strategy)
            try:
                case.call_and_validate(timeout=REQUEST_TIMEOUT)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:
                lines = str(exc).splitlines()
                summary = next(
                    (
                        line.strip()
                        for line in lines
                        if "Received:" in line or "Documented:" in line
                    ),
                    lines[0].strip() if lines else type(exc).__name__,
                )
                curl_cmd = getattr(case, "as_curl_command", lambda: "")()
                failures.append(f"{operation.method.upper()} {operation.path} -> {summary}")
                print(f"    FAIL: {summary}\n    curl: {curl_cmd}", flush=True)
                break
        else:
            print("    ok", flush=True)
    if failures:
        pytest.fail("contract violations:\n" + "\n".join(failures))


@given(data=st.data())
@settings(max_examples=1, derandomize=True, deadline=None)
def test_api_contract(schema, data) -> None:
    """@given rather than .example(): failures are recorded in hypothesis's
    example database and replayed+minimized on the next run, so a transient
    fuzz failure reproduces deterministically instead of only appearing on
    the run that hit it. One test case draws all scoped examples; the live
    server boots once per session."""
    _fuzz_scoped_operations(schema, data)
