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
    # Same guard, against the real tree: changes.sh is known to embed Python.
    assert _blocks((CI / "changes.sh").read_text()), "found no embedded Python to check"
