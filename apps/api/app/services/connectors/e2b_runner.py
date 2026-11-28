"""GAIA Cloud's connector runner: one fresh E2B sandbox per call, killed when the call ends.

The install phase reaches only the registries and download hosts, with no
secret present. Egress is then narrowed to the spec's hosts before the
credential files are written and the call runs. E2B matches "*.domain" in
allow_out against subdomains only, so the apex needs its own entry.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import shlex
import time

from e2b import AsyncSandbox, AuthenticationException, CommandExitException, SandboxException
from e2b.sandbox.filesystem.filesystem import WriteEntry
from e2b.sandbox.network import ALL_TRAFFIC

from app.constants.connectors import (
    CONNECTOR_E2B_PURPOSE,
    CONNECTOR_E2B_TEMPLATE,
    CONNECTOR_INSTALL_TIMEOUT_SECONDS,
    CONNECTOR_REST_HELPER,
    CONNECTOR_SANDBOX_LIFETIME_SECONDS,
)
from app.constants.log_tags import LogTag
from app.constants.providers import CredentialProviderName
from app.services.connectors.install import install_script
from app.services.connectors.rest_helper import REST_HELPER_SOURCE
from app.services.connectors.runner import (
    CappedOutput,
    RunnerFile,
    RunOutcome,
    RunRequest,
    RunResult,
    failed_before_call,
    run_result,
    runner_path,
)
from app.services.providers.provider_credentials_service import resolve as resolve_provider
from shared.py.wide_events import log

_ROOT_USER = "root"
# The sandbox's unprivileged user, who owns its home and runs the call.
_CALL_USER = "user"
# E2B's own command timeout is off: the runner kills at its deadline itself.
_NO_SDK_TIMEOUT = 0


class E2BConnectorRunner:
    """Run each connector call in its own throwaway E2B sandbox."""

    async def run(self, request: RunRequest) -> RunResult:
        started = time.monotonic()
        config = await resolve_provider(CredentialProviderName.E2B)
        if config is None or not config.api_key:
            return failed_before_call(
                RunOutcome.RUNNER_UNAVAILABLE, "no E2B API key is configured", started
            )
        try:
            sandbox = await AsyncSandbox.create(
                template=CONNECTOR_E2B_TEMPLATE,
                timeout=CONNECTOR_SANDBOX_LIFETIME_SECONDS,
                api_key=config.api_key,
                metadata={"purpose": CONNECTOR_E2B_PURPOSE},
                network={
                    "allow_out": sorted({*request.install_hosts, *request.call_hosts}),
                    "deny_out": [ALL_TRAFFIC],
                },
            )
        except (SandboxException, AuthenticationException) as error:
            log.warning(f"{LogTag.SANDBOX} connector sandbox create failed", error=str(error))
            return failed_before_call(
                RunOutcome.RUNNER_UNAVAILABLE, f"E2B sandbox create failed: {error}", started
            )
        try:
            return await _run_in(sandbox, request, started)
        finally:
            await sandbox.kill()


async def _run_in(sandbox: AsyncSandbox, request: RunRequest, started: float) -> RunResult:
    if request.install:
        install = await _run_command(
            sandbox,
            install_script(request.install),
            user=_ROOT_USER,
            envs={},
            deadline_seconds=CONNECTOR_INSTALL_TIMEOUT_SECONDS,
        )
        if install.timed_out:
            return failed_before_call(
                RunOutcome.INSTALL_FAILED,
                f"install did not finish within {CONNECTOR_INSTALL_TIMEOUT_SECONDS}s",
                started,
            )
        if install.exit_code != 0:
            return install.result(RunOutcome.INSTALL_FAILED, started)

    await sandbox.update_network({"allow_out": list(request.call_hosts), "deny_out": [ALL_TRAFFIC]})
    files = [*request.files, RunnerFile(CONNECTOR_REST_HELPER, REST_HELPER_SOURCE)]
    await sandbox.files.write_files(
        [WriteEntry(path=runner_path(f.path), data=f.content) for f in files], user=_CALL_USER
    )

    call = await _run_command(
        sandbox,
        shlex.join(request.argv) + " < /dev/null",
        user=_CALL_USER,
        envs=request.env,
        deadline_seconds=request.timeout_seconds,
    )
    if call.timed_out:
        call.stderr.add(f"\nthe call did not finish within {request.timeout_seconds}s")
        return call.result(RunOutcome.TIMEOUT, started)
    return call.result(RunOutcome.OK if call.exit_code == 0 else RunOutcome.EXIT_NONZERO, started)


@dataclass(frozen=True)
class _Finished:
    """How one sandbox command ended; exit_code is None when it was killed at its deadline."""

    exit_code: int | None
    timed_out: bool
    stdout: CappedOutput
    stderr: CappedOutput

    def result(self, outcome: RunOutcome, started: float) -> RunResult:
        return run_result(outcome, self.exit_code, self.stdout, self.stderr, started)


async def _run_command(
    sandbox: AsyncSandbox,
    command: str,
    *,
    user: str,
    envs: Mapping[str, str],
    deadline_seconds: int,
) -> _Finished:
    """Run a command to its end, killing it at the deadline or once its output passes the cap."""
    stdout, stderr = CappedOutput(), CappedOutput()
    cap_reached = asyncio.Event()
    handle = await sandbox.commands.run(
        command,
        background=True,
        envs=dict(envs),
        user=user,
        timeout=_NO_SDK_TIMEOUT,
        on_stdout=_Collector(stdout, cap_reached),
        on_stderr=_Collector(stderr, cap_reached),
    )
    finished = asyncio.ensure_future(handle.wait())
    cap_hit = asyncio.ensure_future(cap_reached.wait())
    try:
        done, _ = await asyncio.wait(
            {finished, cap_hit}, timeout=deadline_seconds, return_when=asyncio.FIRST_COMPLETED
        )
        if not finished.done():
            await handle.kill()
            await asyncio.wait({finished})
    finally:
        cap_hit.cancel()
    timed_out = not done
    try:
        exit_code = finished.result().exit_code
    except CommandExitException as error:
        exit_code = error.exit_code
    return _Finished(None if timed_out else exit_code, timed_out, stdout, stderr)


class _Collector:
    """An output callback that keeps its stream and signals once the stream passes the cap."""

    def __init__(self, stream: CappedOutput, cap_reached: asyncio.Event) -> None:
        self._stream = stream
        self._cap_reached = cap_reached

    def __call__(self, text: str) -> None:
        self._stream.add(text)
        if self._stream.capped:
            self._cap_reached.set()
