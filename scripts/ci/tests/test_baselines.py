"""baselines.py growth: a ratchet baseline only grows on a founder's written approval.

Driven as a subprocess against a throwaway git repo, the way the repo-policy
lane runs it: the base is a real commit and the head is the working tree.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

CI = Path(__file__).resolve().parent.parent
SCRIPT = CI / "baselines.py"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/tmp",
}

TWINS = "scripts/ci/baselines/api-shape-twins.txt"
SQUIRREL = "scripts/ci/baselines/squirrel-build.txt"
PLR = "tools/lints/plr_complexity_baseline.txt"
LINT = "tools/lints/no_silent_fallback.py"
DUMPS = "tools/lints/tool_dump_boundary.py"
APPROVAL = (
    "# growth approved by founder on 2026-11-18: the twin is fixed by the brief-card refactor"
)

BASE_FILES = {
    TWINS: "# api-schema-types twins. This file only ever shrinks.\n\na.ts:A=AModel\nb.ts:B=BModel\n",
    SQUIRREL: "# squirrel findings\nscore:Content=85\n/home\tcontent/keyword-stuffing\tgaia\n",
    PLR: "# plr baseline\napps/api/app/a.py\tPLR0913\tdeferred-until=2026-12-01; old reason\n",
    LINT: 'ALLOWLIST: frozenset[str] = frozenset(\n    {\n        "app/a.py::probe",\n    }\n)\n',
    DUMPS: 'ALLOWLIST: dict[str, int] = {\n    "app/tool.py::run": 2,\n}\n',
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, env=GIT_ENV, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel, text in BASE_FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "master")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _edit(repo: Path, rel: str, old: str, new: str) -> None:
    path = repo / rel
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "growth", "--base", "master", "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_unchanged_baselines_pass(repo: Path) -> None:
    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no baseline grew" in result.stdout


def test_new_line_fails_at_its_line(repo: Path) -> None:
    _edit(repo, TWINS, "b.ts:B=BModel\n", "b.ts:B=BModel\nc.ts:C=CModel\n")

    result = _run(repo)

    assert result.returncode == 1
    assert f"::error file={TWINS},line=5::new baseline entry `c.ts:C=CModel`" in result.stdout


def test_removed_line_passes(repo: Path) -> None:
    _edit(repo, TWINS, "a.ts:A=AModel\n", "")

    assert _run(repo).returncode == 0


def test_swapping_one_entry_for_another_still_fails(repo: Path) -> None:
    _edit(repo, TWINS, "a.ts:A=AModel\n", "z.ts:Z=ZModel\n")

    result = _run(repo)

    assert result.returncode == 1
    assert "z.ts:Z=ZModel" in result.stdout


def test_approval_written_in_this_change_covers_the_run_below_it(repo: Path) -> None:
    _edit(
        repo,
        TWINS,
        "b.ts:B=BModel\n",
        f"b.ts:B=BModel\n\n{APPROVAL}\nc.ts:C=CModel\nd.ts:D=DModel\n",
    )

    result = _run(repo)

    assert result.returncode == 0, result.stdout


def test_approval_does_not_reach_past_a_blank_line(repo: Path) -> None:
    _edit(
        repo,
        TWINS,
        "b.ts:B=BModel\n",
        f"b.ts:B=BModel\n\n{APPROVAL}\nc.ts:C=CModel\n\nd.ts:D=DModel\n",
    )

    result = _run(repo)

    assert result.returncode == 1
    assert "d.ts:D=DModel" in result.stdout
    assert "c.ts:C=CModel" not in result.stdout


def test_an_approval_already_on_the_base_does_not_approve_new_growth(repo: Path) -> None:
    _edit(repo, TWINS, "a.ts:A=AModel\n", f"{APPROVAL}\na.ts:A=AModel\n")
    _git(repo, "commit", "-qam", "approved earlier growth")
    _edit(repo, TWINS, "a.ts:A=AModel\n", "a.ts:A=AModel\nab.ts:AB=ABModel\n")

    result = _run(repo)

    assert result.returncode == 1
    assert "ab.ts:AB=ABModel" in result.stdout


def test_an_approval_without_a_reason_is_not_an_approval(repo: Path) -> None:
    _edit(
        repo,
        TWINS,
        "b.ts:B=BModel\n",
        "b.ts:B=BModel\n# growth approved by founder on 2026-11-18:\nc.ts:C=CModel\n",
    )

    assert _run(repo).returncode == 1


def test_an_approval_with_an_impossible_date_fails_loud(repo: Path) -> None:
    bad = "# growth approved by founder on 2026-13-40: reason"
    _edit(repo, TWINS, "b.ts:B=BModel\n", f"b.ts:B=BModel\n{bad}\nc.ts:C=CModel\n")

    result = _run(repo)

    assert result.returncode != 0
    assert "no valid date" in result.stderr


@pytest.mark.parametrize(
    ("new_floor", "grew"),
    [("score:Content=80", True), ("score:Content=90", False)],
)
def test_squirrel_score_is_a_floor(repo: Path, new_floor: str, grew: bool) -> None:
    _edit(repo, SQUIRREL, "score:Content=85", new_floor)

    result = _run(repo)

    assert (result.returncode == 1) is grew
    if grew:
        assert "`score:Content=85` -> `score:Content=80`" in result.stdout


def test_renewing_a_deferral_is_not_growth(repo: Path) -> None:
    _edit(repo, PLR, "2026-12-01; old reason", "2027-02-01; renewed: the refactor is scheduled")

    assert _run(repo).returncode == 0


def test_new_allowlist_element_fails_and_an_approval_above_it_passes(repo: Path) -> None:
    _edit(
        repo,
        LINT,
        '        "app/a.py::probe",\n',
        '        "app/a.py::probe",\n        "app/b.py::probe",\n',
    )
    unapproved = _run(repo)
    _edit(
        repo,
        LINT,
        '        "app/b.py::probe",\n',
        f'        {APPROVAL}\n        "app/b.py::probe",\n',
    )
    approved = _run(repo)

    assert unapproved.returncode == 1
    assert (
        f"::error file={LINT},line=4::new baseline entry `'app/b.py::probe'`" in unapproved.stdout
    )
    assert approved.returncode == 0, approved.stdout


@pytest.mark.parametrize(("count", "grew"), [("3", True), ("1", False)])
def test_allowlist_count_is_a_ceiling(repo: Path, count: str, grew: bool) -> None:
    _edit(repo, DUMPS, '"app/tool.py::run": 2', f'"app/tool.py::run": {count}')

    assert (_run(repo).returncode == 1) is grew


def test_a_new_gate_seeding_its_own_baseline_is_not_growth(repo: Path) -> None:
    seeded = repo / "scripts/ci/baselines/new-gate.txt"
    seeded.write_text("# new gate\nx.ts\ny.ts\n")
    _edit(repo, DUMPS, "}\n", '}\n\nNEW_ALLOWLIST: frozenset[str] = frozenset({"x"})\n')

    assert _run(repo).returncode == 0
