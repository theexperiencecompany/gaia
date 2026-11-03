"""lib/mutation_gap.py fails loud on anything but a source mutmut cannot parse.

It decides "nothing to mutate" (a SKIP) versus "changed code no test reaches"
(a red gate). Swallowing every exception turned a mutmut upgrade that broke
create_mutations into a green SKIP for every changed module.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[3]

# Run in the API environment, the one the lane runs it in: it has mutmut and libcst.
PROBE = """
import sys
sys.path.insert(0, {lib!r})
import mutation_gap
{patch}
print(mutation_gap._mutants_on("m.py", {source!r}, {{2}}))
"""


def _probe(source: str, patch: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "--group",
            "dev",
            "python",
            "-c",
            PROBE.format(lib=str(REPO_ROOT / "scripts/ci/lib"), patch=patch, source=source),
        ],
        # mutmut resolves [tool.mutmut] from the cwd, as the lane's workdir copy does.
        cwd=REPO_ROOT / "apps" / "api",
        env={k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_an_unparseable_module_has_nothing_to_mutate() -> None:
    result = _probe("def f(:\n    return 1\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


def test_a_broken_mutmut_fails_instead_of_skipping() -> None:
    result = _probe(
        "def f():\n    return 1\n",
        patch="def boom(*a, **k):\n    raise RuntimeError('mutmut changed shape')\n"
        "mutation_gap.create_mutations = boom",
    )
    assert result.returncode != 0
    assert "mutmut changed shape" in result.stderr
