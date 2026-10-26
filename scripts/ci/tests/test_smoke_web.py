"""smoke-web.sh squirrel: a downloaded binary that is not the pinned build never runs."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "smoke-web.sh"

# Stands in for the release download: writes a binary that would leave a marker if run.
CURL_STUB = """\
#!/usr/bin/env bash
out=""
while [ "$#" -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; *) shift ;; esac
done
printf '#!/usr/bin/env bash\\ntouch "%s"\\n' "$FAKE_STATE/ran" > "$out"
"""


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(CURL_STUB)
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_STATE": str(tmp_path),
        "SQUIRREL_CACHE": str(tmp_path / "cache"),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )


def test_a_download_that_misses_the_pinned_sha256_is_refused(tmp_path: Path) -> None:
    proc = _run(tmp_path, "squirrel")
    assert proc.returncode == 1
    assert "does not match its pinned sha256" in proc.stderr
    assert not (tmp_path / "ran").exists()
    assert [p.suffix for p in (tmp_path / "cache").rglob("squirrel-*")] == [".part"]


def test_a_cached_binary_that_was_swapped_is_downloaded_again_and_refused(tmp_path: Path) -> None:
    _run(tmp_path, "squirrel")
    cached = next((tmp_path / "cache").rglob("*.part"))
    swapped = cached.with_suffix("")
    swapped.write_text(f'#!/usr/bin/env bash\ntouch "{tmp_path}/ran"\n')
    swapped.chmod(0o755)
    proc = _run(tmp_path, "squirrel")
    assert proc.returncode == 1
    assert "does not match its pinned sha256" in proc.stderr
    assert not (tmp_path / "ran").exists()


def test_an_unknown_subcommand_prints_the_usage(tmp_path: Path) -> None:
    proc = _run(tmp_path, "nope")
    assert proc.returncode == 2
    assert "audit | squirrel | audit-build | indexnow" in proc.stderr
