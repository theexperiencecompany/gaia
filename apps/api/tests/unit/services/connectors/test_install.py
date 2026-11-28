"""The install script's shape and hosts, and its checksum gate run for real in a local bash."""

import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

from app.constants.connectors import (
    CONNECTOR_NODE_VERSION,
    NODE_DIST_HOSTS,
    NPM_REGISTRY_HOSTS,
    PIP_REGISTRY_HOSTS,
)
from app.models.connector_models import CpuArch, InstallPackage, PackageManager
from app.services.connectors.install import install_hosts, install_script

_SHA = "a" * 64


def _binary(
    url: str = "https://github.com/o/r/releases/download/v1/tool.tar.gz",
    name: str = "tool",
    sha256: str = _SHA,
    archive_member: str | None = "tool_dir/bin/tool",
    arch: CpuArch | None = None,
) -> InstallPackage:
    return InstallPackage(
        manager=PackageManager.BINARY,
        name=name,
        version="1.0.0",
        url=url,
        sha256=sha256,
        archive_member=archive_member,
        arch=arch,
    )


def _pkg(manager: PackageManager, name: str, version: str = "1.2.3") -> InstallPackage:
    return InstallPackage(manager=manager, name=name, version=version)


def test_install_hosts_cover_each_manager_once_and_sorted() -> None:
    hosts = install_hosts(
        [
            _pkg(PackageManager.PIP, "httpie"),
            _pkg(PackageManager.PIP, "rich"),
            _binary(url="https://dl.example.org/tool"),
        ]
    )

    assert hosts == tuple(sorted({*PIP_REGISTRY_HOSTS, "dl.example.org"}))


def test_npm_reaches_nodejs_org_for_the_pinned_node_and_never_apt() -> None:
    hosts = set(install_hosts([_pkg(PackageManager.NPM, "@scope/cli")]))

    assert hosts == {*NPM_REGISTRY_HOSTS, *NODE_DIST_HOSTS}


def test_npm_packages_install_after_the_pinned_node_for_each_cpu() -> None:
    lines = install_script([_pkg(PackageManager.NPM, "wrangler")]).splitlines()

    node_check = next(i for i, line in enumerate(lines) if '--version)" = v' in line)
    assert f"v{CONNECTOR_NODE_VERSION}" in lines[node_check]
    assert node_check < lines.index("npm install -g --no-fund --no-audit wrangler@1.2.3")
    for dist_arch in ("x64", "arm64"):
        tarball = f"node-v{CONNECTOR_NODE_VERSION}-linux-{dist_arch}.tar.gz"
        assert any(tarball in line and line.startswith("curl ") for line in lines)
    assert sum("sha256sum -c -" in line for line in lines) == 2


def test_a_github_release_binary_reaches_the_asset_hosts_it_redirects_to() -> None:
    hosts = install_hosts([_binary()])

    assert "github.com" in hosts
    assert "release-assets.githubusercontent.com" in hosts


def test_no_packages_reach_no_hosts_and_install_nothing() -> None:
    assert install_hosts([]) == ()
    assert install_script([]).splitlines() == [
        "set -euo pipefail",
        "export DEBIAN_FRONTEND=noninteractive",
    ]


def test_each_manager_installs_exactly_its_pinned_versions() -> None:
    script = install_script(
        [
            _pkg(PackageManager.APT, "jq", "1.6-2.1"),
            _pkg(PackageManager.NPM, "@railway/cli", "3.17.0"),
            _pkg(PackageManager.PIP, "httpie", "3.2.4"),
        ]
    )

    lines = script.splitlines()
    assert lines[0] == "set -euo pipefail"
    assert "apt-get install -y --no-install-recommends jq=1.6-2.1" in lines
    assert lines.index("apt-get update") < lines.index(
        "apt-get install -y --no-install-recommends jq=1.6-2.1"
    )
    assert "npm install -g --no-fund --no-audit @railway/cli@3.17.0" in lines
    assert "python3 -m pip install --no-input --no-cache-dir httpie==3.2.4" in lines


def test_a_binary_url_with_shell_metacharacters_stays_one_quoted_word() -> None:
    url = "https://dl.example.org/a;rm -rf $HOME/tool"
    script = install_script([_binary(url=url, archive_member=None)])

    assert f"'{url}'" in script


@pytest.mark.parametrize(
    ("url", "unpack"),
    [
        ("https://dl.example.org/t.tar.gz", "tar -xzf"),
        ("https://dl.example.org/t.tgz", "tar -xzf"),
        ("https://dl.example.org/t.zip", "unzip -q"),
    ],
)
def test_an_archive_member_is_unpacked_by_its_archive_kind(url: str, unpack: str) -> None:
    script = install_script([_binary(url=url, archive_member="bin/tool")])

    assert unpack in script
    assert 'install -m 0755 "$work"/bin/tool /usr/local/bin/tool' in script


def test_an_archive_member_on_an_unknown_archive_kind_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\.tar\.gz, \.tgz or \.zip"):
        install_script([_binary(url="https://dl.example.org/t.tar.xz")])


def test_a_binary_name_must_be_a_bare_executable_name() -> None:
    with pytest.raises(ValueError, match="bare executable name"):
        install_script([_binary(name="bin/tool")])


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="needs coreutils sha256sum")
def test_a_checksum_mismatch_fails_the_install_before_anything_is_installed(
    tmp_path: Path,
) -> None:
    # A curl stand-in on PATH "downloads" known bytes, so the real sha256sum gate runs offline.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        '#!/bin/bash\nwhile [ "$1" != "-o" ]; do shift; done\nprintf tampered > "$2"\n'
    )
    fake_curl.chmod(0o755)
    marker = tmp_path / "after-checksum"
    expected = hashlib.sha256(b"the real release").hexdigest()
    script = install_script(
        [_binary(url="https://dl.example.org/tool", sha256=expected, archive_member=None)]
    )
    script = script.replace("install -m 0755", f"touch {marker} && install -m 0755")

    ran = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin:/sbin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert ran.returncode != 0
    assert "FAILED" in ran.stdout + ran.stderr
    assert not marker.exists()


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="needs coreutils sha256sum")
def test_a_matching_checksum_passes_the_gate(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        '#!/bin/bash\nwhile [ "$1" != "-o" ]; do shift; done\nprintf genuine > "$2"\n'
    )
    fake_curl.chmod(0o755)
    marker = tmp_path / "after-checksum"
    script = install_script(
        [
            _binary(
                url="https://dl.example.org/tool",
                sha256=hashlib.sha256(b"genuine").hexdigest(),
                archive_member=None,
            )
        ]
    )
    install_line = next(line for line in script.splitlines() if line.startswith("install "))
    script = script.replace(install_line, f"touch {marker}")
    # The stand-in installs nothing, so drop the check that the executable landed.
    script = "\n".join(line for line in script.splitlines() if not line.startswith("[ -x "))

    ran = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin:/sbin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert ran.returncode == 0, ran.stderr
    assert marker.exists()


def test_a_binary_for_another_cpu_is_skipped_and_the_install_fails_naming_the_gap(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uname = bin_dir / "uname"
    fake_uname.write_text("#!/bin/bash\necho aarch64\n")
    fake_uname.chmod(0o755)
    script = install_script([_binary(arch=CpuArch.AMD64)])

    ran = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin:/sbin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert ran.returncode != 0
    assert "no tool build for aarch64" in ran.stderr
    # Skipped before any download: the amd64 build never ran on this CPU.
    assert "curl" not in ran.stderr


def test_each_arch_build_runs_only_on_its_own_cpu() -> None:
    script = install_script([_binary(arch=CpuArch.AMD64), _binary(arch=CpuArch.ARM64)])

    assert 'if [ "$(uname -m)" = x86_64 ]; then' in script
    assert 'if [ "$(uname -m)" = aarch64 ]; then' in script
    assert script.count("[ -x /usr/local/bin/tool ]") == 1
