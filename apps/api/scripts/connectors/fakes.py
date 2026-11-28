"""Local fakes of provider APIs for connectors no team key covers: stripe-mock and LocalStack.

Each fake runs as a container on this machine with its port published, so only the docker
runner reaches it (through host.docker.internal); an E2B sandbox cannot.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
import time

import httpx

_CONTAINER_PREFIX = "gaia-conformance-"
_READY_TIMEOUT_SECONDS = 120
_POLL_SECONDS = 2
# How a docker runner container reaches a port published on this machine.
HOST_FROM_CONTAINER = "host.docker.internal"


class FakeName(StrEnum):
    STRIPE_MOCK = "stripe-mock"
    LOCALSTACK = "localstack"


@dataclass(frozen=True)
class FakeImage:
    image: str
    port: int
    ready_path: str


FAKE_IMAGES: dict[FakeName, FakeImage] = {
    FakeName.STRIPE_MOCK: FakeImage("stripe/stripe-mock:v0.206.0", 12111, "/v1/customers"),
    FakeName.LOCALSTACK: FakeImage("localstack/localstack:2026.11.1", 4566, "/_localstack/health"),
}


def fake_url(name: FakeName) -> str:
    """The fake's base URL as a docker runner container sees it."""
    return f"http://{HOST_FROM_CONTAINER}:{FAKE_IMAGES[name].port}"


async def _docker(*args: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await process.communicate()
    return process.returncode or 0, out.decode(errors="replace").strip()


async def _wait_ready(fake: FakeImage) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    url = f"http://127.0.0.1:{fake.port}{fake.ready_path}"
    async with httpx.AsyncClient(timeout=5) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url, headers={"Authorization": "Bearer sk_test_123"})
                if response.status_code < 500:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(_POLL_SECONDS)
    raise TimeoutError(f"{fake.image} never answered {url}")


@asynccontextmanager
async def _running(name: FakeName) -> AsyncIterator[None]:
    fake = FAKE_IMAGES[name]
    container = f"{_CONTAINER_PREFIX}{name}"
    await _docker("rm", "-f", container)
    code, out = await _docker(
        "run", "-d", "--rm", "--name", container, "-p", f"{fake.port}:{fake.port}", fake.image
    )
    if code != 0:
        raise RuntimeError(f"could not start {fake.image}: {out}")
    try:
        await _wait_ready(fake)
        yield
    finally:
        await _docker("rm", "-f", container)


@asynccontextmanager
async def running_fakes(names: set[FakeName]) -> AsyncIterator[set[FakeName]]:
    """Start each fake, yield the ones that came up, and remove every container afterwards."""
    async with AsyncExitStack() as stack:
        up: set[FakeName] = set()
        for name in sorted(names):
            try:
                await stack.enter_async_context(_running(name))
                up.add(name)
            except (RuntimeError, TimeoutError) as error:
                print(f"fake {name} unavailable: {error}")
        yield up
