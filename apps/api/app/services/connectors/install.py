"""The install phase of a connector runner: one root bash script, and the hosts it reaches.

The script is the same on both backends: E2B runs it in the throwaway sandbox,
the docker runner bakes it into a cached image. It runs before any secret is
present, so nothing it installs can read the user's key at install time.
"""

from collections.abc import Sequence
from enum import StrEnum
import posixpath
import shlex
from urllib.parse import urlsplit

from app.constants.connectors import (
    APT_REGISTRY_HOSTS,
    BINARY_REDIRECT_HOSTS,
    CONNECTOR_BINARY_DIR,
    NPM_REGISTRY_HOSTS,
    PIP_REGISTRY_HOSTS,
)
from app.models.connector_models import CpuArch, InstallPackage, PackageManager

_UNAME_MACHINE = {CpuArch.AMD64: "x86_64", CpuArch.ARM64: "aarch64"}

_SCRIPT_HEADER = ("set -euo pipefail", "export DEBIAN_FRONTEND=noninteractive")

# The base images carry npm on E2B but not in the docker runner's python image;
# Debian's nodejs package brings npm along, so npm needs the apt hosts too.
_ENSURE_NPM = (
    "if ! command -v npm >/dev/null 2>&1; then "
    "apt-get update && apt-get install -y --no-install-recommends nodejs npm; fi"
)


class _ArchiveKind(StrEnum):
    TAR_GZ = "tar_gz"
    ZIP = "zip"


_ARCHIVE_SUFFIXES = (
    (".tar.gz", _ArchiveKind.TAR_GZ),
    (".tgz", _ArchiveKind.TAR_GZ),
    (".zip", _ArchiveKind.ZIP),
)


def install_hosts(packages: Sequence[InstallPackage]) -> tuple[str, ...]:
    """Return every host the install script may reach, sorted and without repeats."""
    hosts: set[str] = set()
    for package in packages:
        match package.manager:
            case PackageManager.NPM:
                hosts.update(NPM_REGISTRY_HOSTS, APT_REGISTRY_HOSTS)
            case PackageManager.PIP:
                hosts.update(PIP_REGISTRY_HOSTS)
            case PackageManager.APT:
                hosts.update(APT_REGISTRY_HOSTS)
            case PackageManager.BINARY:
                host = _binary_url_host(package)
                hosts.update((host, *BINARY_REDIRECT_HOSTS.get(host, ())))
    return tuple(sorted(hosts))


def install_script(packages: Sequence[InstallPackage]) -> str:
    """Return the bash script that installs every package as root, failing on the first error."""
    by_manager = {
        manager: [p for p in packages if p.manager is manager] for manager in PackageManager
    }
    lines = list(_SCRIPT_HEADER)
    if apt := by_manager[PackageManager.APT]:
        specs = " ".join(shlex.quote(f"{p.name}={p.version}") for p in apt)
        lines += ["apt-get update", f"apt-get install -y --no-install-recommends {specs}"]
    if npm := by_manager[PackageManager.NPM]:
        specs = " ".join(shlex.quote(f"{p.name}@{p.version}") for p in npm)
        lines += [_ENSURE_NPM, f"npm install -g --no-fund --no-audit {specs}"]
    if pip := by_manager[PackageManager.PIP]:
        specs = " ".join(shlex.quote(f"{p.name}=={p.version}") for p in pip)
        lines.append(f"python3 -m pip install --no-input --no-cache-dir {specs}")
    binaries = by_manager[PackageManager.BINARY]
    for package in binaries:
        lines += _for_arch(package.arch, _binary_lines(package))
    for executable in dict.fromkeys(p.name for p in binaries):
        # A spec listing no build for this runner's CPU must fail here, not at the call.
        target = shlex.quote(f"{CONNECTOR_BINARY_DIR}/{executable}")
        lines.append(
            f'[ -x {target} ] || {{ echo "no {executable} build for $(uname -m)" >&2; exit 1; }}'
        )
    return "\n".join(lines) + "\n"


def _for_arch(arch: CpuArch | None, lines: list[str]) -> list[str]:
    """Wrap lines so they run only on the runner CPU they are built for."""
    if arch is None:
        return lines
    machine = shlex.quote(_UNAME_MACHINE[arch])
    return [f'if [ "$(uname -m)" = {machine} ]; then', *lines, "fi"]


def _binary_url_host(package: InstallPackage) -> str:
    host = urlsplit(_binary_url(package)).hostname
    if not host:
        raise ValueError(f"binary package {package.name!r} has a url with no host")
    return host


def _binary_url(package: InstallPackage) -> str:
    if package.url is None or package.sha256 is None:
        raise ValueError(f"binary package {package.name!r} needs a url and a sha256")
    return package.url


def _binary_lines(package: InstallPackage) -> list[str]:
    """Download, checksum, unpack and install one binary; a checksum mismatch fails the script."""
    url = _binary_url(package)
    executable = package.name
    if posixpath.basename(executable) != executable:
        raise ValueError(f"binary package name {executable!r} must be a bare executable name")
    target = shlex.quote(f"{CONNECTOR_BINARY_DIR}/{executable}")
    lines = [
        'work="$(mktemp -d)"',
        f'curl -fsSL --proto =https --tlsv1.2 -o "$work/download" {shlex.quote(url)}',
        f'echo {shlex.quote(f"{package.sha256}  ")}"$work/download" | sha256sum -c -',
    ]
    if package.archive_member is None:
        lines.append(f'install -m 0755 "$work/download" {target}')
    else:
        member = shlex.quote(package.archive_member)
        match _archive_kind(url):
            case _ArchiveKind.TAR_GZ:
                lines.append(f'tar -xzf "$work/download" -C "$work" -- {member}')
            case _ArchiveKind.ZIP:
                lines.append(f'unzip -q "$work/download" {member} -d "$work"')
        lines.append(f'install -m 0755 "$work"/{member} {target}')
    lines.append('rm -rf "$work"')
    return lines


def _archive_kind(url: str) -> _ArchiveKind:
    path = urlsplit(url).path.lower()
    for suffix, kind in _ARCHIVE_SUFFIXES:
        if path.endswith(suffix):
            return kind
    raise ValueError(f"archive_member needs a .tar.gz, .tgz or .zip url, got {url!r}")
