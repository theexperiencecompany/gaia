"""browser.sh locate: the browser slice runs with both engines and the proxy, or not at all.

A scenario that skipped for want of an engine would read as a pass, so a missing
Chrome or Obscura, or a Fortress that fails its checksum, must fail the step,
naming which. Chrome is a stub on PATH; the Obscura binary is a file where the
obscura-bin build stage would have exported it; the Fortress and Caddy releases
are tarballs served from file:// URLs, checked against the digests they are pinned to.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile

SCRIPT = Path(__file__).parent.parent / "browser.sh"

CHROME_STUB = """\
#!/usr/bin/env bash
echo "Google Chrome 999.0.0.0"
"""
FORTRESS_STUB = """\
#!/usr/bin/env bash
exec "$(dirname "$0")/chrome" "$@"
"""
CADDY_STUB = """\
#!/usr/bin/env bash
echo "v2.10.2"
"""


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _caddy_release(tmp_path: Path) -> tuple[str, str]:
    """Return a Caddy release tarball's file:// URL and its sha512."""
    stub = tmp_path / "release" / "caddy"
    stub.parent.mkdir()
    _executable(stub, CADDY_STUB)
    archive = tmp_path / "release" / "caddy.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stub, arcname="caddy")
    return archive.as_uri(), hashlib.sha512(archive.read_bytes()).hexdigest()


def _fortress_release(tmp_path: Path) -> tuple[str, str]:
    """Return a Fortress release tarball's file:// URL and its sha256, laid out as the release is."""
    stub = tmp_path / "fortress-release" / "tilion"
    stub.parent.mkdir()
    _executable(stub, FORTRESS_STUB)
    archive = tmp_path / "fortress-release" / "fortress.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stub, arcname="fortress-v156/tilion")
    return archive.as_uri(), hashlib.sha256(archive.read_bytes()).hexdigest()


def _locate(
    tmp_path: Path,
    *,
    chrome: bool,
    obscura: bool,
    caddy_sha512: str | None = None,
    fortress_sha256: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Only what the script runs besides the engines: a host's own Chrome must not be found.
    tools = ("bash", "dirname", "curl", "sed", "uname", "rm", "sha256sum", "sha512sum", "tar")
    for tool in (*tools, "gzip", "mkdir"):
        found = shutil.which(tool)
        assert found is not None
        (bin_dir / tool).symlink_to(found)
    if chrome:
        _executable(bin_dir / "google-chrome", CHROME_STUB)
    runner_temp = tmp_path / "runner"
    (runner_temp / "obscura").mkdir(parents=True)
    if obscura:
        _executable(runner_temp / "obscura" / "obscura", "#!/usr/bin/env bash\n")
    github_env = tmp_path / "github_env"
    github_env.touch()
    release_url, release_sha512 = _caddy_release(tmp_path)
    fortress_url, fortress_sha256_pinned = _fortress_release(tmp_path)
    env = {
        "PATH": str(bin_dir),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_ENV": str(github_env),
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "CADDY_RELEASE_URL": release_url,
        "CADDY_SHA512": caddy_sha512 or release_sha512,
        "FORTRESS_RELEASE_URL": fortress_url,
        "FORTRESS_SHA256": fortress_sha256 or fortress_sha256_pinned,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "locate"], env=env, capture_output=True, text=True, check=False
    )
    return result, github_env


def test_both_engines_are_published_to_the_job(tmp_path: Path) -> None:
    result, github_env = _locate(tmp_path, chrome=True, obscura=True)

    assert result.returncode == 0, result.stderr
    published = dict(line.split("=", 1) for line in github_env.read_text().splitlines())
    assert published["CHROMIUM_BIN"] == str(tmp_path / "bin" / "google-chrome")
    # Fortress stays off for the stack: only its identity test launches it, from FORTRESS_BIN.
    assert "BROWSER_HOST_FORTRESS" not in published
    # Fortress's launcher, unpacked out of the release's versioned top directory.
    assert published["FORTRESS_BIN"] == str(tmp_path / "runner" / "fortress" / "tilion")
    assert published["OBSCURA_BIN"] == str(tmp_path / "runner" / "obscura" / "obscura")
    assert published["CADDY_BIN"] == str(tmp_path / "runner" / "caddy" / "caddy")


def test_a_caddy_release_that_fails_its_checksum_is_never_published(tmp_path: Path) -> None:
    result, github_env = _locate(tmp_path, chrome=True, obscura=True, caddy_sha512="0" * 128)

    assert result.returncode != 0
    assert "failed its checksum" in result.stdout + result.stderr
    assert "CADDY_BIN" not in github_env.read_text()


def test_a_missing_obscura_fails_naming_where_it_looked(tmp_path: Path) -> None:
    result, github_env = _locate(tmp_path, chrome=True, obscura=False)

    assert result.returncode != 0
    assert "no Obscura binary" in result.stdout + result.stderr
    assert github_env.read_text() == ""


def test_a_fortress_release_that_fails_its_checksum_is_never_published(tmp_path: Path) -> None:
    result, github_env = _locate(tmp_path, chrome=True, obscura=True, fortress_sha256="0" * 64)

    assert result.returncode != 0
    assert re.search(r"fortress \S+ failed its checksum", result.stdout + result.stderr)
    assert "FORTRESS_BIN" not in github_env.read_text()


def test_a_missing_chrome_fails(tmp_path: Path) -> None:
    result, github_env = _locate(tmp_path, chrome=False, obscura=True)

    assert result.returncode != 0
    assert "google-chrome is not on this runner" in result.stdout + result.stderr
    assert github_env.read_text() == ""
