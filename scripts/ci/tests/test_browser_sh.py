"""browser.sh locate: the browser slice runs with both engines or not at all.

A scenario that skipped for want of an engine would read as a pass, so a missing
Chrome or Obscura must fail the step that looks for them, naming which one.
Chrome is a stub on PATH; the Obscura binary is a file where the obscura-bin
build stage would have exported it.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

SCRIPT = Path(__file__).parent.parent / "browser.sh"

CHROME_STUB = """\
#!/usr/bin/env bash
echo "Google Chrome 999.0.0.0"
"""


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _locate(
    tmp_path: Path, *, chrome: bool, obscura: bool
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Only what the script runs besides the engines: a host's own Chrome must not be found.
    for tool in ("bash", "dirname"):
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
    env = {
        "PATH": str(bin_dir),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_ENV": str(github_env),
        "HOME": os.environ.get("HOME", str(tmp_path)),
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
    assert published["OBSCURA_BIN"] == str(tmp_path / "runner" / "obscura" / "obscura")


def test_a_missing_obscura_fails_naming_where_it_looked(tmp_path: Path) -> None:
    result, github_env = _locate(tmp_path, chrome=True, obscura=False)

    assert result.returncode != 0
    assert "no Obscura binary" in result.stdout + result.stderr
    assert github_env.read_text() == ""


def test_a_missing_chrome_fails(tmp_path: Path) -> None:
    result, github_env = _locate(tmp_path, chrome=False, obscura=True)

    assert result.returncode != 0
    assert "google-chrome is not on this runner" in result.stdout + result.stderr
    assert github_env.read_text() == ""
