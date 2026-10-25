"""Leave a file per mutant while its forked child is inside a test body.

The file holds the running test's node id and is removed when the body
returns or raises, so one left behind means the child was killed mid-test: a
real timeout. A child that died outside every test body (the chromadb client
that cannot survive fork() dies in fixture setup) leaves none.

Loaded into mutmut's pytest runs by mutation.py through pytest_add_cli_args;
MUTMUT_IN_TEST_DIR names the directory, and only a mutant child writes there.
"""

from __future__ import annotations

from collections.abc import Generator
import os
from pathlib import Path

import pytest

IN_TEST_DIR_ENV = "MUTMUT_IN_TEST_DIR"
MUTANT_MARK = "__mutmut_"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    mutant = os.environ.get("MUTANT_UNDER_TEST", "")
    if MUTANT_MARK not in mutant:
        return (yield)
    marker = Path(os.environ[IN_TEST_DIR_ENV]) / mutant
    marker.write_text(item.nodeid)
    try:
        return (yield)
    finally:
        marker.unlink()
