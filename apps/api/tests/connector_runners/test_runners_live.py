"""Both connector runners against the real thing: E2B sandboxes and the local docker daemon."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
import subprocess
import time

import pytest

from app.constants.connectors import CONNECTOR_RAW_OUTPUT_MAX_BYTES
from app.models.connector_models import InstallPackage, PackageManager
from app.services.connectors.docker_runner import DockerConnectorRunner
from app.services.connectors.e2b_runner import E2BConnectorRunner
from app.services.connectors.install import install_hosts
from app.services.connectors.rest_helper import (
    AUTH_HEADER_ENV,
    AUTH_TEMPLATE_ENV,
    BASE_URL_ENV,
    REST_HELPER_ARGV,
    SECRET_ENV,
)
from app.services.connectors.runner import (
    ConnectorRunner,
    RunnerFile,
    RunOutcome,
    RunRequest,
    RunResult,
)

_GH_VERSION = "2.106.0"
# From the release's gh_2.106.0_checksums.txt.
_GH_SHA256 = {
    "amd64": "a476449fa9625413c54a3734eded62e9e480e49f421ff08e7f3b3879c059a033",
    "arm64": "5e8a0c51e1a8345f36bd0b8bb88604b6a5388df16f3ab3e3b9b6d794fa223a67",
}
_DOCKER_ARCH = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}
_GITHUB_API = "api.github.com"
# Generous against a cold sandbox, far under the runner's own 90 s call bound.
_PROMPT_SECONDS = 30


@dataclass(frozen=True)
class _Backend:
    name: str
    runner: ConnectorRunner
    arch: str


def _docker_arch() -> str:
    reported = subprocess.run(
        ["docker", "info", "--format", "{{.Architecture}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return _DOCKER_ARCH[reported]


@pytest.fixture(params=["e2b", "docker"])
def backend(request: pytest.FixtureRequest) -> _Backend:
    if request.param == "e2b":
        # E2B sandboxes are x86_64.
        return _Backend("e2b", E2BConnectorRunner(), "amd64")
    return _Backend("docker", DockerConnectorRunner(), _docker_arch())


@pytest.fixture(scope="session")
def gh_token() -> str:
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    token = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()
    assert token, "gh auth token printed nothing; run gh auth login"
    return token


def _gh(arch: str, sha256: str | None = None) -> InstallPackage:
    return InstallPackage(
        manager=PackageManager.BINARY,
        name="gh",
        version=_GH_VERSION,
        url=(
            f"https://github.com/cli/cli/releases/download/v{_GH_VERSION}/"
            f"gh_{_GH_VERSION}_linux_{arch}.tar.gz"
        ),
        sha256=sha256 or _GH_SHA256[arch],
        archive_member=f"gh_{_GH_VERSION}_linux_{arch}/bin/gh",
    )


def _request(
    argv: tuple[str, ...],
    *,
    install: tuple[InstallPackage, ...] = (),
    call_hosts: tuple[str, ...] = (_GITHUB_API,),
    env: Mapping[str, str] | None = None,
    files: tuple[RunnerFile, ...] = (),
    timeout_seconds: int = 60,
) -> RunRequest:
    return RunRequest(
        install=install,
        install_hosts=install_hosts(install),
        call_hosts=call_hosts,
        argv=argv,
        timeout_seconds=timeout_seconds,
        env=env or {},
        files=files,
    )


async def _timed(runner: ConnectorRunner, request: RunRequest) -> tuple[RunResult, float]:
    started = time.monotonic()
    result = await runner.run(request)
    return result, time.monotonic() - started


async def test_a_pinned_binary_installs_and_runs(backend: _Backend) -> None:
    result = await backend.runner.run(_request(("gh", "--version"), install=(_gh(backend.arch),)))

    assert result.outcome is RunOutcome.OK, result.stderr
    assert f"gh version {_GH_VERSION}" in result.stdout


async def test_gh_reads_the_account_with_the_token_in_its_env(
    backend: _Backend, gh_token: str
) -> None:
    result = await backend.runner.run(
        _request(("gh", "api", "user"), install=(_gh(backend.arch),), env={"GH_TOKEN": gh_token})
    )

    assert result.outcome is RunOutcome.OK, result.stderr
    assert json.loads(result.stdout)["login"]


async def test_gh_lists_repos_read_only(backend: _Backend, gh_token: str) -> None:
    result = await backend.runner.run(
        _request(
            ("gh", "api", "user/repos?per_page=3"),
            install=(_gh(backend.arch),),
            env={"GH_TOKEN": gh_token},
        )
    )

    assert result.outcome is RunOutcome.OK, result.stderr
    assert isinstance(json.loads(result.stdout), list)


async def test_a_bad_token_exits_nonzero(backend: _Backend) -> None:
    result = await backend.runner.run(
        _request(
            ("gh", "api", "user"),
            install=(_gh(backend.arch),),
            env={"GH_TOKEN": "ghp_" + "0" * 36},
        )
    )

    assert result.outcome is RunOutcome.EXIT_NONZERO
    assert result.exit_code not in (None, 0)
    assert "401" in result.stdout + result.stderr


async def test_a_bad_checksum_fails_the_install(backend: _Backend) -> None:
    result = await backend.runner.run(
        _request(("gh", "--version"), install=(_gh(backend.arch, sha256="0" * 64),))
    )

    assert result.outcome is RunOutcome.INSTALL_FAILED
    assert "FAILED" in result.stdout + result.stderr


async def test_a_nonexistent_npm_version_fails_the_install(backend: _Backend) -> None:
    missing = InstallPackage(manager=PackageManager.NPM, name="cowsay", version="999.999.999")

    result = await backend.runner.run(_request(("cowsay", "hi"), install=(missing,)))

    assert result.outcome is RunOutcome.INSTALL_FAILED
    assert "cowsay@999.999.999" in result.stdout + result.stderr


@pytest.mark.parametrize("argv", [("cat",), ("bash", "-c", "read -r line; echo status=$?")])
async def test_a_command_waiting_on_stdin_gets_eof_at_once(
    backend: _Backend, argv: tuple[str, ...]
) -> None:
    result, seconds = await _timed(backend.runner, _request(argv))

    assert result.outcome is RunOutcome.OK, result.stderr
    assert seconds < _PROMPT_SECONDS
    assert result.stdout in ("", "status=1\n")


async def test_a_command_demanding_a_tty_fails_fast(backend: _Backend) -> None:
    result, seconds = await _timed(
        backend.runner, _request(("python3", "-c", "open('/dev/tty').read()"))
    )

    assert result.outcome is RunOutcome.EXIT_NONZERO
    assert seconds < _PROMPT_SECONDS


async def test_huge_output_is_capped(backend: _Backend) -> None:
    result = await backend.runner.run(_request(("bash", "-c", "yes | head -c 20000000")))

    assert result.output_capped
    assert len(result.stdout.encode()) == CONNECTOR_RAW_OUTPUT_MAX_BYTES


async def test_a_call_past_its_timeout_is_stopped(backend: _Backend) -> None:
    result, seconds = await _timed(backend.runner, _request(("sleep", "120"), timeout_seconds=3))

    assert result.outcome is RunOutcome.TIMEOUT
    assert seconds < _PROMPT_SECONDS
    if backend.name == "docker":
        assert _connector_containers() == []


async def test_two_concurrent_calls_each_see_only_their_own_env_and_files(
    backend: _Backend,
) -> None:
    def call(tag: str) -> RunRequest:
        return _request(
            ("bash", "-c", 'echo "env=$CALL_TAG"; cat ~/.call/tag; ls ~/.call'),
            env={"CALL_TAG": tag},
            files=(RunnerFile(f"~/.call/{tag}", tag), RunnerFile("~/.call/tag", f"file={tag}")),
        )

    first, second = await asyncio.gather(
        backend.runner.run(call("alpha")), backend.runner.run(call("bravo"))
    )

    assert first.outcome is RunOutcome.OK and second.outcome is RunOutcome.OK
    assert first.stdout == "env=alpha\nfile=alphaalpha\ntag\n"
    assert second.stdout == "env=bravo\nfile=bravobravo\ntag\n"


async def test_the_rest_helper_calls_a_real_api_with_the_key(
    backend: _Backend, gh_token: str
) -> None:
    result = await backend.runner.run(
        _request(
            (*REST_HELPER_ARGV, "GET", "/user"),
            env={
                BASE_URL_ENV: f"https://{_GITHUB_API}",
                SECRET_ENV: gh_token,
                AUTH_HEADER_ENV: "Authorization",
                AUTH_TEMPLATE_ENV: "Bearer {secret}",
            },
        )
    )

    assert result.outcome is RunOutcome.OK, result.stderr
    assert json.loads(result.stdout)["login"]
    assert result.stderr.strip() == "HTTP 200"


async def test_the_rest_helper_refuses_a_host_escape_path(backend: _Backend, gh_token: str) -> None:
    result = await backend.runner.run(
        _request(
            (*REST_HELPER_ARGV, "GET", "//example.com/steal"),
            env={
                BASE_URL_ENV: f"https://{_GITHUB_API}",
                SECRET_ENV: gh_token,
                AUTH_HEADER_ENV: "Authorization",
                AUTH_TEMPLATE_ENV: "Bearer {secret}",
            },
        )
    )

    assert (result.outcome, result.exit_code) == (RunOutcome.EXIT_NONZERO, 2)
    assert result.stdout == ""


async def test_e2b_denies_a_host_outside_the_call_hosts() -> None:
    runner = E2BConnectorRunner()
    probe = ("curl", "-sS", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}")

    allowed = await runner.run(_request((*probe, f"https://{_GITHUB_API}/zen")))
    denied = await runner.run(_request((*probe, "https://example.com/")))

    assert (allowed.outcome, allowed.stdout) == (RunOutcome.OK, "200")
    assert denied.outcome is RunOutcome.EXIT_NONZERO


async def test_docker_never_puts_the_secret_in_a_host_process_argv() -> None:
    secret = "connector-secret-" + os.urandom(8).hex()  # pragma: allowlist secret
    call = asyncio.create_task(
        DockerConnectorRunner().run(
            _request(
                ("bash", "-c", 'sleep 4; test "$TOKEN" = "$EXPECTED"'),
                env={"TOKEN": secret, "EXPECTED": secret},
                files=(RunnerFile("~/.cred", secret),),
            )
        )
    )
    seen_docker_run = False
    deadline = time.monotonic() + _PROMPT_SECONDS
    while not call.done() and time.monotonic() < deadline:
        processes = await _host_process_args()
        seen_docker_run = seen_docker_run or "gaia-connector-" in processes
        assert secret not in processes
        await asyncio.sleep(0.2)

    result = await call
    assert seen_docker_run
    assert result.outcome is RunOutcome.OK, result.stderr


async def _host_process_args() -> str:
    ps = await asyncio.create_subprocess_exec(
        "ps", "-axww", "-o", "args=", stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await ps.communicate()
    return stdout.decode(errors="replace")


def _connector_containers() -> list[str]:
    listed = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=gaia.connector=call", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return listed.split()
