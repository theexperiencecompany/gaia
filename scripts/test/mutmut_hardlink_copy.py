"""Hardlink mutmut's ``also_copy`` tree into ``mutants/`` instead of duplicating it.

mutmut 3.7 has no configuration for this — verified in the installed source.
``mutmut.configuration`` appends ``tests/``, ``pyproject.toml`` and the
lockfiles to whatever ``also_copy`` names, so emptying the setting does not stop
the copy, and ``__main__.copy_also_copy_files`` calls ``shutil.copytree``
unconditionally with no copy-function or link option. For this repo that is a
second 43 MB / 2100-file duplication of ``app`` + ``tests`` + ``scripts`` on top
of the one the shard already staged.

Hardlinks are safe because nothing writes through them: the only file mutmut
writes inside ``mutants/`` is the mutated module, and ``copy_src_dir`` has
already put a REAL copy of it there before this runs. Leaving an existing
destination alone is therefore what keeps the mutated file private — and it is
the same precedence ``copy_src_dir`` itself uses.

Loaded into the mutmut process by mutation.sh via PYTHONPATH, alongside
mutmut_decorated_patch and mutmut_diff_scope.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from mutmut import __main__ as mutmut_main
from mutmut.configuration import Config


def _link(src: str, dst: str, *, follow_symlinks: bool = True) -> None:
    """Hardlink src to dst, leaving an existing dst untouched.

    Signature mirrors shutil.copy2 so copytree can call it. Falls back to a real
    copy when the link cannot be made (a cross-device also_copy entry).
    """
    if Path(dst).exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst, follow_symlinks=follow_symlinks)


def _copy_also_copy_files() -> None:
    """Mutmut 3.7.0's copy_also_copy_files with os.link doing the copying."""
    for entry in Config.get().also_copy:
        path = Path(entry)
        if not path.exists():
            continue
        destination = Path("mutants") / path
        if path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            _link(str(path), str(destination))
        else:
            shutil.copytree(path, destination, dirs_exist_ok=True, copy_function=_link)


mutmut_main.copy_also_copy_files = _copy_also_copy_files
