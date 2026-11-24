"""lib/mutation_gap.py fails loud on anything but a source mutmut cannot parse.

It decides "nothing to mutate" (a SKIP) versus "changed code no test reaches"
(a red gate). Swallowing every exception turned a mutmut upgrade that broke
create_mutations into a green SKIP for every changed module.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import mutation
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Run in the API environment, the one the lane runs it in: it has mutmut and libcst.
PROBE = """
import sys
sys.path.insert(0, {lib!r})
import mutation_gap
{patch}
print(mutation_gap._mutants_on("m.py", {source!r}, {{2}}))
"""


def _probe(workdir: Path, source: str, patch: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT / "apps" / "api"),
            "--frozen",
            "--group",
            "dev",
            "python",
            "-c",
            PROBE.format(lib=str(REPO_ROOT / "scripts/ci/lib"), patch=patch, source=source),
        ],
        # mutmut resolves [tool.mutmut] from the cwd: the workdir configure_mutmut wrote.
        cwd=workdir,
        env={k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "probe"\n')
    request = mutation.ModuleRequest(module="m.py", testfiles=("test_m.py",), ranges="[[2,2]]")
    mutation.configure_mutmut(request, tmp_path)
    return tmp_path


def test_an_unparseable_module_has_nothing_to_mutate(workdir: Path) -> None:
    result = _probe(workdir, "def f(:\n    return 1\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


def test_a_broken_mutmut_fails_instead_of_skipping(workdir: Path) -> None:
    result = _probe(
        workdir,
        "def f():\n    return 1\n",
        patch="def boom(*a, **k):\n    raise RuntimeError('mutmut changed shape')\n"
        "mutation_gap.create_mutations = boom",
    )
    assert result.returncode != 0
    assert "mutmut changed shape" in result.stderr
