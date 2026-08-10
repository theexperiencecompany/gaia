"""Make the logcheck module importable for its own tests (pytest rootdir mode)."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
