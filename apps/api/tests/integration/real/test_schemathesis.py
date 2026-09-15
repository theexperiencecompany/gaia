"""Schemathesis contract gate for the real API, driven over HTTP.

Boots the REAL GAIA app as a subprocess (uvicorn app.main:app) with real
Postgres/Redis/Mongo/Chroma in Docker and the dev-auth bypass, then fuzzes
SCOPED_OPERATIONS below from the live OpenAPI schema — asserting no 5xx,
schema-valid responses, and no undocumented status codes on those paths.

DOCUMENTED FINDINGS (full-schema exploratory fuzz, SCHEMA_FUZZ_FULL=1),
tracked for the API-hardening follow-up: undocumented 429 plan-gates on
@tiered_rate_limit endpoints; 405-vs-422 shadowing where parameterized
routes shadow literal siblings; undocumented 403 on disconnected
integrations; undocumented 307/410/404 on OAuth/tool-result/not-found
paths; and a server wedge under pathological input, not reproducible via
hand-written curl. SCHEMA_FUZZ_FULL=1 also raises SCHEMA_FUZZ_EXAMPLES.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
from redis import Redis

from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.db.repositories.plans import PlansRepository
from app.db.repositories.subscriptions import SubscriptionsRepository
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
# `import app.main` + lifespan boot costs ~18s warm on a developer laptop; a
# cold 2-core CI runner is several times that, which is how the old 60s
# budget failed here while passing locally.
BOOT_TIMEOUT = float(os.environ.get("SCHEMA_FUZZ_BOOT_TIMEOUT", "300"))
# Generous per-probe timeout: a slow first response must not be misread as "not
# listening yet" (the poll loop still exits as soon as one probe succeeds).
PROBE_TIMEOUT = float(os.environ.get("SCHEMA_FUZZ_PROBE_TIMEOUT", "10"))


def _pick_port() -> int:
    """Pick a free ephemeral port, or use SCHEMA_FUZZ_PORT where one must be fixed (e.g. a firewall allowlist)."""
    if env_port := os.environ.get("SCHEMA_FUZZ_PORT"):
        return int(env_port)
    return pick_free_port()


PORT = _pick_port()

# Operations that demonstrably pass — the gate's scope. Notes/todos/reminders
# are excluded: embedding-dependent paths need a real GOOGLE_API_KEY the
# hermetic test fence blanks, and that group hits the server-wedge finding above.
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
    """Return the end of the server's log, for a failure message.

    A 4 KiB tail showed only the shutdown sequence and the re-raised aggregate
    error, not the line naming the provider that actually failed.
    """
    try:
        return log_path.read_text(errors="replace")[-limit:] or "<server produced no output>"
    except OSError as exc:
        return f"<could not read server log {log_path}: {exc}>"


@pytest.fixture(scope="session")
def _seeded_startup_requirements(mongodb_url: str) -> Iterator[None]:
    """Satisfy the app's own startup gate before booting it.

    startup_validation.py aborts boot when subscription_plans is empty; CI's
    Mongo is empty. Only inserted into an empty collection, and only the
    inserted row is removed afterwards.
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


def _make_fuzz_user_pro(
    mongodb_url: str, redis_url: str, user_id: str
) -> tuple[MongoClient, object]:
    """Give the fuzz user a real active subscription, and return it for cleanup.

    EntitlementMiddleware 402s non-PRO callers, which 402 is not a documented
    status, so a free fuzz user would hide every handler behind a paywall.
    Seeded via the subscriptions collection rather than bypassed, so it
    exercises the real gate.
    """
    client: MongoClient = MongoClient(mongodb_url)
    now = datetime.now(UTC)
    inserted = client[MONGO_DATABASE_NAME][SubscriptionsRepository.collection_name].insert_one(
        {
            "dodo_subscription_id": f"sub_schemathesis_{user_id}",
            "user_id": user_id,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
    )
    # The plan is Redis-cached for five minutes, so a FREE entry left by an
    # earlier run against the same Redis would outlive this row and re-402 the
    # whole fuzz. Dropped here, and again on teardown.
    redis_client = Redis.from_url(redis_url)
    try:
        redis_client.delete(f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}")
    finally:
        redis_client.close()
    return client, inserted.inserted_id


def _fail_if_parallel() -> None:
    """Refuse to run under xdist, naming the cause.

    This test owns a whole uvicorn process and must not compete with xdist
    workers for the runner's cores; pytest.ini's addopts carry -n 4.
    """
    workers = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))
    if workers > 1:
        pytest.fail(
            f"this suite must run serially, but pytest started {workers} xdist workers. "
            "Pass --override-ini=addopts=--strict-markers (pytest.ini's addopts carry -n 4), "
            "or run it via `nx run api:test:schemathesis`."
        )


@contextmanager
def _uvicorn_process(log_path: Path) -> Iterator[subprocess.Popen[bytes]]:
    """Run the real app under uvicorn, terminated on the way out.

    Output goes to a file rather than subprocess.PIPE: nothing drains a pipe
    during the readiness poll, so a full 64 KiB pipe buffer would block the
    server mid-boot.
    """
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
        try:
            yield proc
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _wait_until_serving(proc: subprocess.Popen[bytes], url: str, log_path: Path) -> None:
    """Poll /openapi.json until the server answers, or explain why it never did."""
    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"API server exited early (code {proc.returncode}):\n{_tail(log_path)}"
            )
        try:
            if httpx.get(f"{url}/openapi.json", timeout=PROBE_TIMEOUT).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(
        f"API server did not become ready in {BOOT_TIMEOUT:.0f}s "
        f"(raise SCHEMA_FUZZ_BOOT_TIMEOUT if the host is simply slow):"
        f"\n{_tail(log_path)}"
    )


def _mint_dev_user(url: str, log_path: Path) -> str:
    """Create the user the dev-auth bypass authenticates every request as.

    The bypass authenticates every request as DEV_USER; that user must exist in
    Mongo (the dev router is idempotent). Retries with backoff — the server
    being up is already proven by the readiness poll.
    """
    mint_error: Exception | None = None
    for attempt in range(3):
        try:
            mint = httpx.post(f"{url}/api/v1/dev/users", json={"email": DEV_USER}, timeout=30)
            mint.raise_for_status()
            return str(mint.json()["id"])
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            mint_error = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not mint dev user after 3 attempts: {mint_error}\n{_tail(log_path)}")


@contextmanager
def _pro_subscription(mongodb_url: str, redis_url: str, fuzz_user_id: str) -> Iterator[None]:
    """Give the fuzz user a Pro plan for the session, then take it back.

    The API is paid-only, so a free fuzz user would 402 on most of the scoped
    operations and the gate would assert nothing.
    """
    subscription_client, subscription_id = _make_fuzz_user_pro(mongodb_url, redis_url, fuzz_user_id)
    try:
        yield
    finally:
        subscription_client[MONGO_DATABASE_NAME][
            SubscriptionsRepository.collection_name
        ].delete_one({"_id": subscription_id})
        subscription_client.close()
        redis_client = Redis.from_url(redis_url)
        try:
            redis_client.delete(f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{fuzz_user_id}")
        finally:
            redis_client.close()


@pytest.fixture(scope="session")
def live_api_url(
    _seeded_startup_requirements: None, mongodb_url: str, redis_url: str
) -> Iterator[str]:
    """Boot the real API in a subprocess and wait until it serves /openapi.json."""
    _fail_if_parallel()

    log_dir = Path(tempfile.mkdtemp(prefix="schemathesis-server-"))
    log_path = log_dir / "server.log"
    url = f"http://127.0.0.1:{PORT}"

    try:
        with _uvicorn_process(log_path) as proc:
            _wait_until_serving(proc, url, log_path)
            fuzz_user_id = _mint_dev_user(url, log_path)
            with _pro_subscription(mongodb_url, redis_url, fuzz_user_id):
                yield url
    finally:
        shutil.rmtree(log_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def schema(live_api_url: str):
    import schemathesis

    return schemathesis.openapi.from_url(f"{live_api_url}/openapi.json")


def _fuzz_scoped_operations(schema, data) -> None:
    """Assert no 5xx, schema-valid responses, and no undocumented status codes on the scoped operations (or all operations under SCHEMA_FUZZ_FULL=1)."""
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
    """@given records failures in hypothesis's example database for deterministic replay on the next run."""
    _fuzz_scoped_operations(schema, data)
