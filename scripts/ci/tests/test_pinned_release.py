"""lib/pinned-release.sh fetch_cached: the box's tool cache serves a pinned tarball, never trusts it."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

LIB = Path(__file__).resolve().parent.parent / "lib"


def fetch_cached(url: str, digest: str, cache: Path) -> subprocess.CompletedProcess[str]:
    script = f'source "{LIB}/log.sh"; source "{LIB}/pinned-release.sh"; fetch_cached tool "$@"'
    return subprocess.run(
        ["bash", "-c", script, "fetch", url, "sha256", digest, str(cache)],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def release(tmp_path: Path, body: bytes) -> tuple[str, str]:
    asset = tmp_path / "release" / "tool.tar.gz"
    asset.parent.mkdir()
    asset.write_bytes(body)
    return asset.as_uri(), hashlib.sha256(body).hexdigest()


def test_a_cached_tarball_matching_its_pin_is_served_without_a_download(tmp_path: Path) -> None:
    url, digest = release(tmp_path, b"pinned")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "tool.tar.gz").write_bytes(b"pinned")
    (tmp_path / "release" / "tool.tar.gz").unlink()

    proc = fetch_cached(url, digest, cache)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(cache / "tool.tar.gz")


def test_a_cached_tarball_that_no_longer_matches_is_fetched_again(tmp_path: Path) -> None:
    url, digest = release(tmp_path, b"pinned")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "tool.tar.gz").write_bytes(b"corrupt")

    proc = fetch_cached(url, digest, cache)

    assert proc.returncode == 0, proc.stderr
    assert (cache / "tool.tar.gz").read_bytes() == b"pinned"


def test_a_download_that_never_matches_fails_and_caches_nothing(tmp_path: Path) -> None:
    url, _ = release(tmp_path, b"tampered")
    cache = tmp_path / "cache"

    proc = fetch_cached(url, hashlib.sha256(b"pinned").hexdigest(), cache)

    assert proc.returncode != 0
    assert not (cache / "tool.tar.gz").exists()
