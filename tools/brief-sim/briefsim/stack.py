"""Boot the real GAIA stack (API + ARQ worker) and the fake world on the simulated clock, isolated.

Isolation on a shared machine: its own Mongo database, Redis DB, Postgres database, RabbitMQ
vhost and Chroma collection suffix, and its own ports. The only credential read is
OPENAI_API_KEY (Infisical development) for the LLM lane; everything outside GAIA is the
fake world. Every process is stopped on exit, error or signal.
"""

import base64
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

import httpx
import psycopg
from pymongo import MongoClient
import redis

REPO = Path(__file__).resolve().parents[3]
API_DIR = REPO / "apps" / "api"
CLOCKBOOT = REPO / "tools" / "brief-sim" / "clockboot"
SIM_PKG = REPO / "tools" / "brief-sim"
INFISICAL_PROJECT = "24c7bfd2-a378-417e-beb5-58e8eed23c6e"
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "brief_sim"
REDIS_URL = "redis://localhost:6379/13"
POSTGRES_ADMIN = "postgresql://postgres:postgres@localhost:5432/postgres"
POSTGRES_DB = "brief_sim"
POSTGRES_URL = f"postgresql://postgres:postgres@localhost:5432/{POSTGRES_DB}"
RABBIT_VHOST = "brief_sim"
RABBIT_ADMIN = "http://localhost:15672/api"
API_PORT = 8710
WORLD_PORT = 8711
BYPASS_EMAIL = "delivered+brief-sim@resend.dev"
LLM_MODEL = "gpt-6-luna"
_BOOT_TIMEOUT_S = 600.0
_INFRA = {"mongo": 27017, "redis": 6379, "postgres": 5432, "rabbitmq": 5672, "chroma": 8080}


class StackError(RuntimeError):
    """The stack could not boot, or a process died while the run needed it."""


@dataclass(frozen=True)
class Stack:
    api: str
    world: str
    env: dict[str, str]
    processes: dict[str, subprocess.Popen[bytes]]

    def check_alive(self) -> None:
        for name, process in self.processes.items():
            if process.poll() is not None:
                raise StackError(f"{name} exited with {process.returncode}; see logs/{name}.log")


def _port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _require_infra() -> None:
    down = [name for name, port in _INFRA.items() if not _port_open(port)]
    if down:
        raise StackError(f"infra not running: {down}; start it with `nx run docker:docker:up`")
    taken = [port for port in (API_PORT, WORLD_PORT) if _port_open(port)]
    if taken:
        raise StackError(f"ports {taken} are taken; stop whatever holds them")


def _openai_key() -> str:
    exported = subprocess.run(
        [
            "infisical",
            "export",
            "--projectId",
            INFISICAL_PROJECT,
            "--env",
            "development",
            "--format=json",
            "--silent",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for secret in json.loads(exported):
        if secret["key"] == "OPENAI_API_KEY":
            return str(secret["value"])
    raise StackError("OPENAI_API_KEY is not in Infisical development")


def _reset_stores() -> None:
    MongoClient(MONGO_URI).drop_database(MONGO_DB)
    redis.Redis.from_url(REDIS_URL).flushdb()
    with httpx.Client(auth=("guest", "guest"), timeout=10) as rabbit:
        rabbit.delete(f"{RABBIT_ADMIN}/vhosts/{RABBIT_VHOST}")
        rabbit.put(f"{RABBIT_ADMIN}/vhosts/{RABBIT_VHOST}").raise_for_status()
        rabbit.put(
            f"{RABBIT_ADMIN}/permissions/{RABBIT_VHOST}/guest",
            json={"configure": ".*", "write": ".*", "read": ".*"},
        ).raise_for_status()
    with psycopg.connect(POSTGRES_ADMIN, autocommit=True) as postgres:
        postgres.execute(f"DROP DATABASE IF EXISTS {POSTGRES_DB} WITH (FORCE)")
        postgres.execute(f"CREATE DATABASE {POSTGRES_DB}")


def sim_env(clock: Path, openai_key: str) -> dict[str, str]:
    """Return the environment every simulated process runs with: sandbox defaults plus the sim's world."""
    world = f"http://127.0.0.1:{WORLD_PORT}"
    env = {k: v for k, v in os.environ.items() if k not in {"VIRTUAL_ENV", "PYTHONPATH"}}
    env.update(
        {
            "ENV": "development",
            "DEV_AUTH_BYPASS_EMAIL": BYPASS_EMAIL,
            "MONGO_DB": MONGO_URI,
            "MONGO_DB_NAME": MONGO_DB,
            "REDIS_URL": REDIS_URL,
            "POSTGRES_URL": POSTGRES_URL,
            "RABBITMQ_URL": f"amqp://guest:guest@localhost:5672/{RABBIT_VHOST}",
            "CHROMADB_HOST": "127.0.0.1",
            "CHROMADB_PORT": "8080",
            "GAIA_CHROMA_COLLECTION_SUFFIX": "_briefsim",
            "WORKOS_API_KEY": "sim-workos-key",
            "WORKOS_CLIENT_ID": "client_sim",
            "WORKOS_COOKIE_PASSWORD": "s" * 32,
            "MCP_ENCRYPTION_KEY": base64.b64encode(b"brief-sim-encryption-key-32bytes").decode(),
            "AGENT_SECRET": secrets.token_hex(16),
            "BOT_SESSION_TOKEN_SECRET": secrets.token_hex(16),
            "COMPOSIO_KEY": "sim-composio-key",
            "COMPOSIO_BASE_URL": world,
            "COMPOSIO_WEBHOOK_SECRET": secrets.token_hex(16),
            "CLOUDINARY_CLOUD_NAME": "brief-sim",
            "CLOUDINARY_API_KEY": "sim",
            "CLOUDINARY_API_SECRET": "sim",
            "CLOUDINARY_UPLOAD_PREFIX": world,
            # Files and edition images go to the world's S3 (on GAIA Cloud they go to R2, one S3 client).
            "BLOB_STORE": "s3",
            "S3_ENDPOINT_URL": f"{world}/s3",
            "S3_BUCKET": "brief-sim",
            "S3_ACCESS_KEY_ID": "sim",
            "S3_SECRET_ACCESS_KEY": "sim",
            "S3_ADDRESSING_STYLE": "path",
            # The fake S3 takes plain bodies, not aws-chunked uploads with trailing checksums.
            "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
            "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required",
            "RESEND_API_KEY": "re_sim",
            "RESEND_API_URL": world,
            "RESEND_AUDIENCE_ID": "sim-audience",
            "EMAIL_UNSUBSCRIBE_SECRET": secrets.token_hex(16),
            "DODO_WEBHOOK_PAYMENTS_SECRET": "whsec_"
            + base64.b64encode(secrets.token_bytes(24)).decode(),
            "DEV_DEFAULT_MODEL": "custom",
            "DEV_LLM_BASE_URL": "https://api.openai.com/v1",
            "DEV_LLM_API_KEY": openai_key,
            "DEV_LLM_MODEL": LLM_MODEL,
            "DEV_LLM_API": "responses",
            "LOG_FORMAT": "json",
            "LOG_LEVEL": os.environ.get("BRIEF_SIM_LOG_LEVEL", "WARNING"),
            "ARQ_METRICS_PORT": "0",
            # A clock jump leaves every cron behind; ARQ catches up one missed run per poll.
            "ARQ_POLL_DELAY_SECONDS": "0.02",
            "MCP_USE_ANONYMIZED_TELEMETRY": "false",
            "BRIEF_SIM_CLOCK": str(clock),
            "PYTHONPATH": f"{CLOCKBOOT}:{SIM_PKG}",
        }
    )
    for unset in (
        "POSTHOG_PROJECT_TOKEN",
        "POSTHOG_HOST",
        "SENTRY_DSN",
        "OPENROUTER_API_KEY",
        "INFISICAL_TOKEN",
    ):
        env.pop(unset, None)
    return env


def _spawn(
    name: str, command: list[str], env: dict[str, str], logs: Path, cwd: Path
) -> subprocess.Popen[bytes]:
    sink = (logs / f"{name}.log").open("ab")
    return subprocess.Popen(
        command, cwd=cwd, env=env, stdout=sink, stderr=subprocess.STDOUT, start_new_session=True
    )


def _uv(*args: str) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        str(API_DIR),
        "--frozen",
        "--group",
        "backend",
        "--group",
        "dev",
        *args,
    ]


def _wait_until(
    what: str, ready: Callable[[], bool], processes: dict[str, subprocess.Popen[bytes]]
) -> None:
    deadline = time.monotonic() + _BOOT_TIMEOUT_S
    while not ready():
        for name, process in processes.items():
            if process.poll() is not None:
                raise StackError(
                    f"{name} exited with {process.returncode} while waiting for {what}; see logs/{name}.log"
                )
        if time.monotonic() > deadline:
            raise StackError(f"{what} not ready after {_BOOT_TIMEOUT_S:.0f}s")
        time.sleep(1)


def _api_healthy(api: str) -> bool:
    try:
        return httpx.get(f"{api}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _worker_healthy() -> bool:
    client = redis.Redis.from_url(REDIS_URL)
    return any(True for _ in client.scan_iter(match="arq:health:*", count=100))


@contextmanager
def running_stack(out: Path, clock: Path, origin: str, days: int) -> Iterator[Stack]:
    """Reset the sim stores, boot world -> API -> worker on the clock, and stop them all on exit."""
    _require_infra()
    _reset_stores()
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = sim_env(clock, _openai_key())
    processes: dict[str, subprocess.Popen[bytes]] = {}
    api, world = f"http://127.0.0.1:{API_PORT}", f"http://127.0.0.1:{WORLD_PORT}"
    try:
        processes["world"] = _spawn(
            "world",
            _uv(
                "python",
                "-m",
                "briefsim.world.server",
                "--port",
                str(WORLD_PORT),
                "--out",
                str(out),
                "--origin",
                origin,
                "--days",
                str(days),
            ),
            env,
            logs,
            SIM_PKG,
        )
        processes["api"] = _spawn(
            "api",
            _uv("uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT)),
            env,
            logs,
            API_DIR,
        )
        _wait_until("the world", lambda: _port_open(WORLD_PORT), processes)
        _wait_until("the API", lambda: _api_healthy(api), processes)
        # Under the dev bypass every request without X-Dev-User (webhooks too) is this user.
        httpx.post(
            f"{api}/api/v1/dev/users", json={"email": BYPASS_EMAIL, "name": "Brief Sim"}, timeout=30
        ).raise_for_status()
        processes["worker"] = _spawn(
            "worker",
            _uv(
                "arq",
                "app.worker.WorkerSettings",
                "--custom-log-dict",
                "app.workers.config.log_config.ARQ_LOG_CONFIG",
            ),
            env,
            logs,
            API_DIR,
        )
        _wait_until("the ARQ worker", _worker_healthy, processes)
        yield Stack(api=f"{api}/api/v1", world=world, env=env, processes=processes)
    finally:
        for process in processes.values():
            if process.poll() is None:
                os.killpg(process.pid, 15)
        for process in processes.values():
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, 9)
