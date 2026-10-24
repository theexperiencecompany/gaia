"""Narrow a parsed YAML or JSON value, failing the test when the document holds another shape."""

from __future__ import annotations

from typing import Any


def mapping(value: object) -> dict[str, Any]:
    """Return value as a mapping, or fail naming what the document held instead."""
    assert isinstance(value, dict), f"expected a mapping, got {value!r:.200}"
    return value


def sequence(value: object) -> list[Any]:
    """Return value as a list, or fail naming what the document held instead."""
    assert isinstance(value, list), f"expected a list, got {value!r:.200}"
    return value
