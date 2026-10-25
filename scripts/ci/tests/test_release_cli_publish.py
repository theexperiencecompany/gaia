"""release.sh dispatch-cli-publish: a publish is failed only when it really failed.

``gh``, ``npm`` and ``sleep`` are fakes on PATH that replay a scripted sequence
of answers, one per call, so the real polling loop runs in milliseconds. Two
false failures shipped: a single ``gh run list`` blip read as "no publish is
running", and npm's registry read lagging the publish that had just finished —
either one reported a CLI release that succeeded as a failed one.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

CI = Path(__file__).parent.parent
SCRIPT = CI / "release.sh"

# Each fake answers with the next line of its plan; the last line repeats.
REPLAY = """\
next_answer() {
  local plan="$STATE/$1" n
  n=$(cat "$plan.n" 2>/dev/null || echo 0)
  echo $((n + 1)) > "$plan.n"
  sed -n "$((n + 1))p" "$plan" | grep . || tail -n 1 "$plan"
}
"""

GH_STUB = (
    "#!/usr/bin/env bash\n"
    + REPLAY
    + """\
case "$1 $2" in
  "workflow run") exit 0 ;;
  "run list")
    answer=$(next_answer gh)
    [ "$answer" = fail ] && { echo "HTTP 502" >&2; exit 1; }
    echo "$answer" ;;
esac
"""
)

NPM_STUB = (
    "#!/usr/bin/env bash\n"
    + REPLAY
    + """\
[ "$(next_answer npm)" = present ] && { echo 1.2.3; exit 0; }
echo "npm error code E404" >&2
exit 1
"""
)


def _publish(tmp_path: Path, *, gh: list[str], npm: list[str]) -> subprocess.CompletedProcess[str]:
    state = tmp_path / "state"
    state.mkdir()
    (state / "gh").write_text("\n".join(gh) + "\n")
    (state / "npm").write_text("\n".join(npm) + "\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("gh", GH_STUB), ("npm", NPM_STUB), ("sleep", "#!/bin/sh\n")):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), "dispatch-cli-publish"],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(state),
            "GH_TOKEN": "t0ken",
            "TAG": "cli-v1.2.3",
            "VERSION": "1.2.3",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_a_version_the_registry_shows_late_is_still_a_success(tmp_path: Path) -> None:
    result = _publish(
        tmp_path, gh=["1", "0"], npm=["absent", "absent", "absent", "absent", "present"]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "published" in result.stdout


def test_a_failed_run_listing_is_not_read_as_a_finished_publish(tmp_path: Path) -> None:
    result = _publish(
        tmp_path, gh=["1", "fail", "1"], npm=["absent", "absent", "absent", "present"]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "published" in result.stdout


def test_a_publish_that_never_lands_still_fails(tmp_path: Path) -> None:
    result = _publish(tmp_path, gh=["1", "0"], npm=["absent"])
    assert result.returncode != 0
    assert "Publish finished but @heygaia/cli@1.2.3 is not on npm" in result.stderr
