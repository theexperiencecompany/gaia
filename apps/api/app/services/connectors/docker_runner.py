"""Self-host's connector runner: one fresh local docker container per call, removed when it ends.

The install phase happens once per package set, at image build time: the image
is derived from the local sandbox image and tagged by the hash of everything
baked into it, so a call reuses it and an edit to any input builds a new one.
"""

import asyncio
from encodings.utf_8 import IncrementalDecoder
import hashlib
import io
from pathlib import Path
import re
import tarfile
import time
import uuid

from app.constants.connectors import (
    CONNECTOR_DOCKER_CONTAINER_PREFIX,
    CONNECTOR_DOCKER_CPUS,
    CONNECTOR_DOCKER_IMAGE_REPOSITORY,
    CONNECTOR_DOCKER_LABEL,
    CONNECTOR_DOCKER_MEMORY_LIMIT,
    CONNECTOR_DOCKER_PIDS_LIMIT,
    CONNECTOR_DOCKER_USER,
    CONNECTOR_INSTALL_TIMEOUT_SECONDS,
)
from app.constants.log_tags import LogTag
from app.constants.sandbox import LOCAL_SANDBOX_NETWORK, SANDBOX_USER_HOME
from app.models.connector_models import InstallPackage
from app.services.connectors.install import install_script
from app.services.connectors.rest_helper import REST_HELPER_PATH, REST_HELPER_SOURCE
from app.services.connectors.runner import (
    CappedOutput,
    RunOutcome,
    RunRequest,
    RunResult,
    capped,
    failed_before_call,
    run_result,
    runner_path,
)
from app.services.connectors.scripts import docker_entrypoint
from app.services.connectors.scripts.docker_entrypoint import (
    PAYLOAD_ENV,
    PayloadFile,
    encode_payload,
)
from app.services.sandbox.local_sandbox import (
    LOCAL_SANDBOX_IMAGE,
    LocalSandboxError,
    ensure_sandbox_image,
    ensure_sandbox_network,
    run_docker,
    spawn_process,
)
from shared.py.wide_events import log

_IMAGE_LIB_DIR = "/usr/local/lib/gaia-connector"
_ENTRYPOINT_PATH = f"{_IMAGE_LIB_DIR}/entrypoint.py"
_INSTALL_PATH = f"{_IMAGE_LIB_DIR}/install.sh"
# A build step's own output line: "#6 0.432 no gh build for aarch64".
_STEP_TIMED_LINE = re.compile(r"^\d+\.\d+ ")
_ENTRYPOINT_SOURCE = Path(docker_entrypoint.__file__).read_text(encoding="utf-8")
_STREAM_CHUNK_BYTES = 65_536

_build_locks: dict[str, asyncio.Lock] = {}


class DockerConnectorRunner:
    """Run each connector call in its own throwaway local container.

    Docker has no per-host egress allowlist, so a call reaches any host the
    sandbox network does and call_hosts is not enforced here. The REST helper's
    own host lock is what keeps a REST connector's key on its base URL's host.
    """

    async def run(self, request: RunRequest) -> RunResult:
        started = time.monotonic()
        try:
            await ensure_sandbox_image()
            await ensure_sandbox_network()
        except (LocalSandboxError, FileNotFoundError) as error:
            return failed_before_call(
                RunOutcome.RUNNER_UNAVAILABLE, f"local docker is unavailable: {error}", started
            )
        image = connector_image(request.install)
        build_failed = await _ensure_image(image, request.install, started)
        if build_failed is not None:
            return build_failed
        return await _call(image, request, started)


def connector_image(packages: tuple[InstallPackage, ...]) -> str:
    """Return the image tag a package set's calls run in."""
    digest = hashlib.sha256(_build_context(packages)).hexdigest()
    return f"{CONNECTOR_DOCKER_IMAGE_REPOSITORY}:{digest[:12]}"


def _dockerfile() -> str:
    return "\n".join(
        (
            f"FROM {LOCAL_SANDBOX_IMAGE}",
            f"LABEL {CONNECTOR_DOCKER_LABEL}=image",
            f"COPY install.sh {_INSTALL_PATH}",
            f"RUN bash {_INSTALL_PATH} && rm -f {_INSTALL_PATH}",
            f"COPY entrypoint.py {_ENTRYPOINT_PATH}",
            f"COPY gaia_rest.py {REST_HELPER_PATH}",
            "",
        )
    )


def _build_context(packages: tuple[InstallPackage, ...]) -> bytes:
    """Return the build context tar; deterministic, so its hash names the image."""
    members = {
        "Dockerfile": _dockerfile(),
        "install.sh": install_script(packages),
        "entrypoint.py": _ENTRYPOINT_SOURCE,
        "gaia_rest.py": REST_HELPER_SOURCE,
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in members.items():
            data = text.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


async def _ensure_image(
    image: str, packages: tuple[InstallPackage, ...], started: float
) -> RunResult | None:
    """Build the call image unless it exists; None when it is ready, else the install failure."""
    async with _build_locks.setdefault(image, asyncio.Lock()):
        rc, _, _ = await run_docker("image", "inspect", "--format", "{{.Id}}", image)
        if rc == 0:
            return None
        context = _build_context(packages)
        proc = await spawn_process(
            ["docker", "build", "--progress=plain", "--tag", image, "-"], stdin=context
        )
        try:
            async with asyncio.timeout(CONNECTOR_INSTALL_TIMEOUT_SECONDS):
                stdout, stderr = await proc.communicate(context)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return failed_before_call(
                RunOutcome.INSTALL_FAILED,
                f"install did not finish within {CONNECTOR_INSTALL_TIMEOUT_SECONDS}s",
                started,
            )
        if proc.returncode != 0:
            return run_result(
                RunOutcome.INSTALL_FAILED,
                proc.returncode,
                capped(stdout.decode(errors="replace")),
                capped(install_step_output(stderr.decode(errors="replace"))),
                started,
            )
        log.info(f"{LogTag.SANDBOX} built a connector image", image=image)
        return None


def install_step_output(build_log: str) -> str:
    """Return what the install script printed, out of a plain-progress docker build log.

    The script's own words ("no gh build for aarch64", a checksum mismatch) are what say
    how to fix it; the rest of the log is docker's. The whole log when the step never ran.
    """
    step = re.search(rf"^(#\d+) \[[^\]]*\] RUN bash {re.escape(_INSTALL_PATH)}", build_log, re.M)
    if step is None:
        return build_log
    prefix = f"{step.group(1)} "
    lines = [
        line.removeprefix(prefix).split(" ", 1)[-1]
        for line in build_log.splitlines()
        if line.startswith(prefix) and _STEP_TIMED_LINE.match(line.removeprefix(prefix))
    ]
    return "\n".join(lines) or build_log


def _run_argv(name: str, image: str, call_argv: tuple[str, ...]) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        f"{CONNECTOR_DOCKER_LABEL}=call",
        "--network",
        LOCAL_SANDBOX_NETWORK,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(CONNECTOR_DOCKER_PIDS_LIMIT),
        "--memory",
        CONNECTOR_DOCKER_MEMORY_LIMIT,
        "--memory-swap",
        CONNECTOR_DOCKER_MEMORY_LIMIT,
        "--cpus",
        CONNECTOR_DOCKER_CPUS,
        "--user",
        CONNECTOR_DOCKER_USER,
        "--workdir",
        SANDBOX_USER_HOME,
        "--env",
        f"HOME={SANDBOX_USER_HOME}",
        # Bare name: docker reads the value from its own environment, never from argv.
        "--env",
        PAYLOAD_ENV,
        "--init",
        image,
        "python3",
        _ENTRYPOINT_PATH,
        *call_argv,
    ]


async def _call(image: str, request: RunRequest, started: float) -> RunResult:
    """Run argv in a fresh container; a timeout or the output cap removes it."""
    name = f"{CONNECTOR_DOCKER_CONTAINER_PREFIX}{uuid.uuid4().hex[:12]}"
    payload = encode_payload(
        request.env,
        (PayloadFile(path=runner_path(f.path), content=f.content) for f in request.files),
    )
    proc = await spawn_process(
        _run_argv(name, image, request.argv), extra_env={PAYLOAD_ENV: payload}
    )
    # spawn_process always pipes both streams; this only narrows the types.
    assert proc.stdout is not None and proc.stderr is not None  # pragma: no mutate
    stdout, stderr = CappedOutput(), CappedOutput()
    cap_reached = asyncio.Event()
    pumps = [
        asyncio.create_task(_pump(proc.stdout, stdout, cap_reached)),
        asyncio.create_task(_pump(proc.stderr, stderr, cap_reached)),
    ]
    exited = asyncio.create_task(proc.wait())
    cap_hit = asyncio.create_task(cap_reached.wait())
    try:
        done, _ = await asyncio.wait(
            {exited, cap_hit}, timeout=request.timeout_seconds, return_when=asyncio.FIRST_COMPLETED
        )
        timed_out = not done
        if not exited.done():
            await _remove(name)
        exit_code = await exited
        await asyncio.gather(*pumps)
    finally:
        cap_hit.cancel()
        if proc.returncode is None:
            await _remove(name)
            proc.kill()
    if timed_out:
        stderr.add(f"\nthe call did not finish within {request.timeout_seconds}s")
        return run_result(RunOutcome.TIMEOUT, None, stdout, stderr, started)
    if exit_code != 0:
        return run_result(RunOutcome.EXIT_NONZERO, exit_code, stdout, stderr, started)
    return run_result(RunOutcome.OK, 0, stdout, stderr, started)


async def _pump(
    stream: asyncio.StreamReader, output: CappedOutput, cap_reached: asyncio.Event
) -> None:
    """Read a stream to its end, keeping it up to the cap and draining past it so docker never blocks."""
    decoder = IncrementalDecoder(errors="replace")
    while chunk := await stream.read(_STREAM_CHUNK_BYTES):
        output.add(decoder.decode(chunk))
        if output.capped:
            cap_reached.set()
    output.add(decoder.decode(b"", final=True))


async def _remove(name: str) -> None:
    rc, _, stderr = await run_docker("rm", "-f", name)
    if rc != 0:
        raise LocalSandboxError(f"docker rm failed for {name}: {stderr.strip()}")
