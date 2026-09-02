"""Python embedded in the CI shell scripts must actually be valid Python.

The consolidation moved script bodies into `cmd_*` functions, which indented
them — including the bodies of `python3 -c '...'` string literals and `python -
<<EOF` heredocs. Shell does not care; Python rejects a leading indent on its
first statement with `IndentationError: unexpected indent`, and the only place
that surfaced was a red lane (all four mutation shards, run 33301137445).

`bash -n` cannot see this: the shell syntax is fine. So compile every embedded
block instead.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest

CI = Path(__file__).resolve().parent.parent
SHELL_SCRIPTS = sorted(CI.glob("*.sh")) + sorted((CI / "lib").glob("*.sh"))

# `python3 -c '` / `-c "` at end of line opens an inline body that runs to the
# next line starting with that quote. Single-line `-c '...'` is not matched and
# does not need to be: it cannot carry a leading indent.
OPEN_C = re.compile(r"""(?:python3?|"\$VENV_PY"|\$PYTHON) -c ('|")$""")
# `python3 - <<'EOF'` / `<<EOF` heredocs, whose body runs to the terminator.
OPEN_HEREDOC = re.compile(r"""(?:python3?|"\$VENV_PY") - .*<<-?\s*['"]?([A-Za-z_]\w*)['"]?""")


def _blocks(text: str) -> list[tuple[int, str]]:
    """Every embedded Python body in one script, as (start line, source)."""
    lines = text.split("\n")
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m_c, m_h = OPEN_C.search(line), OPEN_HEREDOC.search(line)
        if m_c:
            quote, body, i = m_c.group(1), [], i + 1
            start = i
            while i < len(lines) and not lines[i].lstrip().startswith(quote):
                body.append(lines[i])
                i += 1
            # The closing line may carry trailing Python before the quote.
            if i < len(lines):
                body.append(lines[i].split(quote, 1)[0])
            found.append((start + 1, "\n".join(body)))
        elif m_h:
            tag, body, i = m_h.group(1), [], i + 1
            start = i
            while i < len(lines) and lines[i].strip() != tag:
                body.append(lines[i])
                i += 1
            found.append((start + 1, "\n".join(body)))
        i += 1
    return found


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_embedded_python_compiles(script: Path) -> None:
    for lineno, source in _blocks(script.read_text()):
        # Shell expansions ($VAR) are not Python; skip a block that uses them
        # rather than assert on a template. Every block here is plain Python.
        if re.search(r"\$\{?\w", source):
            continue
        try:
            compile(source, f"{script.name}:{lineno}", "exec")
        except SyntaxError as exc:
            pytest.fail(f"{script}:{lineno} embeds invalid Python: {exc}")


def test_the_detector_would_catch_an_indented_block(tmp_path: Path) -> None:
    # The control: without this, a detector that found no blocks at all would
    # make every test above pass vacuously.
    bad = "cmd_x() {\n  python3 -c '\n  import json\n  print(json)\n'\n}\n"
    (lineno, source), *rest = _blocks(bad)
    assert not rest
    with pytest.raises(SyntaxError):
        compile(source, "bad", "exec")


def test_at_least_one_real_block_was_found() -> None:
    # Same guard, against the real tree: mutation.sh is known to embed Python.
    assert _blocks((CI / "mutation.sh").read_text()), "found no embedded Python to check"


def test_the_mutation_shard_parses_a_real_group(tmp_path: Path) -> None:
    """Run `mutation.sh shard` far enough to prove its GROUP parser works.

    The shard fails afterwards (the module does not exist), which is the point:
    reaching that failure means the embedded Python ran. An IndentationError
    instead stops at "could not read its GROUP".
    """
    group = (
        '[{"module":"app/does_not_exist.py",'
        '"testfiles":"[\\"tests/unit/test_nope.py\\"]","ranges":"[[1,2]]"}]'
    )
    proc = subprocess.run(
        ["bash", str(CI / "mutation.sh"), "shard"],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(tmp_path),
            "GROUP": group,
            "SHARD_LOG": str(tmp_path / "shard.log"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    combined = proc.stdout + proc.stderr
    assert "IndentationError" not in combined, combined[-2000:]
    assert "could not read its GROUP" not in combined, combined[-2000:]
    # It got past the parser and into the per-module loop.
    assert "=== app/does_not_exist.py ===" in (tmp_path / "shard.log").read_text()
