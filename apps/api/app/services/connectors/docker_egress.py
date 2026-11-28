"""Self-host connector egress: a call's only way out is a proxy that reaches the spec's hosts.

Each call gets its own internal docker network, which has no route out and no
DNS for outside names, and one squid container on that network and the sandbox
bridge. Squid allows CONNECT to port 443 of the call's hosts and nothing else,
and never sees inside the TLS. A tool that ignores the proxy env reaches nothing.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import re

from app.constants.connectors import (
    CONNECTOR_DOCKER_LABEL,
    CONNECTOR_EGRESS_PROXY_BINARY,
    CONNECTOR_EGRESS_PROXY_IMAGE,
    CONNECTOR_EGRESS_PROXY_MEMORY_LIMIT,
    CONNECTOR_EGRESS_PROXY_PIDS_LIMIT,
    CONNECTOR_EGRESS_PROXY_PORT,
)
from app.constants.sandbox import LOCAL_SANDBOX_NETWORK
from app.services.sandbox.local_sandbox import LocalSandboxError, run_docker

_CONFIG_ENV = "SQUID_CONF"
_WILDCARD = "*."
_HTTPS_PORT = 443
_PROXY_ENV_NAMES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_NO_PROXY_ENV_NAMES = ("NO_PROXY", "no_proxy")
# Node's fetch reads the proxy env only when told to; needs Node 24+, which install.py ships.
_NODE_PROXY_ENV = "NODE_USE_ENV_PROXY"


@dataclass(frozen=True)
class EgressProxy:
    """Where a call's container joins, and the env that points its clients at the proxy."""

    network: str
    env: dict[str, str]


def host_pattern(host: str) -> str:
    """Return the anchored regex for one allowed host; "*.x.com" matches subdomains only."""
    if host.startswith(_WILDCARD):
        return rf"^.+\.{re.escape(host.removeprefix(_WILDCARD))}$"
    return rf"^{re.escape(host)}$"


def squid_config(call_hosts: tuple[str, ...]) -> str:
    """Return a squid config that tunnels to the call's hosts on 443 and refuses everything else.

    -n stops squid from matching an IP literal by its reverse DNS name.
    """
    lines = [
        f"http_port {CONNECTOR_EGRESS_PROXY_PORT}",
        "acl connect_method method CONNECT",
        f"acl https_port port {_HTTPS_PORT}",
    ]
    if call_hosts:
        patterns = " ".join(host_pattern(host) for host in call_hosts)
        lines += [
            f"acl call_hosts dstdom_regex -n -i {patterns}",
            "http_access allow connect_method https_port call_hosts",
        ]
    lines += [
        "http_access deny all",
        "cache deny all",
        "access_log none",
        "cache_log stdio:/dev/stderr",
        "pid_filename none",
        "pinger_enable off",
        "shutdown_lifetime 0 seconds",
    ]
    return "\n".join(lines) + "\n"


async def _docker(*args: str) -> None:
    rc, _, stderr = await run_docker(*args)
    if rc != 0:
        raise LocalSandboxError(f"docker {args[0]} {args[1]} failed: {stderr.strip()}")


def _proxy_argv(name: str, call_hosts: tuple[str, ...]) -> list[str]:
    return [
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"{CONNECTOR_DOCKER_LABEL}=proxy",
        "--network",
        LOCAL_SANDBOX_NETWORK,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        CONNECTOR_EGRESS_PROXY_MEMORY_LIMIT,
        "--pids-limit",
        str(CONNECTOR_EGRESS_PROXY_PIDS_LIMIT),
        "--env",
        f"{_CONFIG_ENV}={squid_config(call_hosts)}",
        "--entrypoint",
        "sh",
        CONNECTOR_EGRESS_PROXY_IMAGE,
        "-c",
        f'printf "%s" "${_CONFIG_ENV}" > /tmp/squid.conf && '
        f"exec {CONNECTOR_EGRESS_PROXY_BINARY} -N -f /tmp/squid.conf",
    ]


def _proxy_env(proxy_name: str) -> dict[str, str]:
    url = f"http://{proxy_name}:{CONNECTOR_EGRESS_PROXY_PORT}"
    env = dict.fromkeys(_PROXY_ENV_NAMES, url)
    env.update(dict.fromkeys(_NO_PROXY_ENV_NAMES, ""))
    env[_NODE_PROXY_ENV] = "1"
    return env


@asynccontextmanager
async def egress_proxy(call_id: str, call_hosts: tuple[str, ...]) -> AsyncIterator[EgressProxy]:
    """Stand up a call's internal network and its proxy, and tear both down when the call ends."""
    network = f"{call_id}-net"
    proxy = f"{call_id}-proxy"
    await _docker(
        "network", "create", "--internal", "--label", f"{CONNECTOR_DOCKER_LABEL}=egress", network
    )
    try:
        await _docker(*_proxy_argv(proxy, call_hosts))
        try:
            await _docker("network", "connect", network, proxy)
            yield EgressProxy(network=network, env=_proxy_env(proxy))
        finally:
            await _docker("rm", "--force", proxy)
    finally:
        await _docker("network", "rm", network)
