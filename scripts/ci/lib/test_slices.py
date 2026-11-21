"""The test-python slices lib/test-slices.json defines, and which of them own a test file."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

SLICES_FILE = Path(__file__).with_name("test-slices.json")


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


@dataclass(frozen=True)
class Slice:
    """One slice: its paths and --ignore flags together say what it runs (paths relative to apps/api)."""

    name: str
    paths: tuple[str, ...]
    ignore: tuple[str, ...]
    services: bool

    def owns(self, path: str) -> bool:
        return any(_under(path, p) for p in self.paths) and not any(
            _under(path, i) for i in self.ignore
        )


def load(slices_file: Path = SLICES_FILE) -> list[Slice]:
    return [
        Slice(
            name=s["name"],
            paths=tuple(s["paths"].split()),
            ignore=tuple(flag.removeprefix("--ignore=") for flag in s["ignore"].split()),
            services=s["services"] == "true",
        )
        for s in json.loads(slices_file.read_text())["slices"]
    ]


def needs_services(path: str, slices: list[Slice]) -> bool:
    """Return False only when service-free slices alone own the path; an unowned file needs services."""
    owners = [s for s in slices if s.owns(path)]
    return not owners or any(s.services for s in owners)
