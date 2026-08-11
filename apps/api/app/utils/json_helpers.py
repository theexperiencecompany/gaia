"""Typed accessors for foreign JSON payloads (external APIs, Mongo bags).

When a payload's shape is known but not *owned* — Notion blocks, Reddit
listings, gmail envelopes, weather responses — the honest read pattern is a
boundary check, not an assumed type: ``_text(bag, "id")`` checks at runtime
and falls back to a default, exactly like ``bag.get("id", "")`` did, but
narrows the static type so the rest of the code is checked.

Never use these to *write*: they return a copy-or-reference read view.

Mypy note: ``dict[str, object]`` is the honest JSON-bag type; these accessors
are the checked bridge from it to the typed slots the caller needs.
"""

from collections.abc import Mapping

__all__ = [
    "dict_bag",
    "list_bag",
    "text_bag",
    "text_opt_bag",
    "int_bag",
    "int_opt_bag",
    "float_bag",
    "bool_bag",
    "int_str_bag",
]


def dict_bag(bag: Mapping[str, object], key: str) -> dict[str, object]:
    """The nested object under ``key``, or {} when absent or not an object."""
    value = bag.get(key)
    return value if isinstance(value, dict) else {}


def list_bag(bag: Mapping[str, object], key: str) -> list[object]:
    """The list under ``key``, or [] when absent or not a list."""
    value = bag.get(key)
    return value if isinstance(value, list) else []


def text_bag(bag: Mapping[str, object], key: str, default: str = "") -> str:
    """The string under ``key``, or ``default`` when absent or not a string."""
    value = bag.get(key)
    return value if isinstance(value, str) else default


def text_opt_bag(bag: Mapping[str, object], key: str) -> str | None:
    """The string under ``key``, or None when absent or not a string.

    ``text_bag`` with ``None`` as the fallback: use when the caller must
    distinguish "absent" from "empty" (e.g. optional API parameters).
    """
    value = bag.get(key)
    return value if isinstance(value, str) else None


def int_str_bag(bag: Mapping[str, object], key: str, default: int = 0) -> int:
    """The int under ``key``, accepting numeric strings (gmail millis pattern).

    Some payloads (gmail ``internalDate``) serialize integers as strings; this
    converts them like ``int(value)`` would, falling back to ``default`` when
    the value is absent, not numeric, or not convertible.
    """
    value = bag.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def int_opt_bag(bag: Mapping[str, object], key: str) -> int | None:
    """The int under ``key``, or None when absent or not an int."""
    value = bag.get(key)
    return value if isinstance(value, int) else None


def float_bag(bag: Mapping[str, object], key: str, default: float = 0.0) -> float:
    """The float under ``key``, or ``default`` when absent or not a float.

    ints are accepted too (they are valid floats at runtime and in JSON).
    """
    value = bag.get(key)
    return value if isinstance(value, (float, int)) else default


def int_bag(bag: Mapping[str, object], key: str, default: int = 0) -> int:
    """The int under ``key``, or ``default`` when absent or not an int."""
    value = bag.get(key)
    return value if isinstance(value, int) else default


def bool_bag(bag: Mapping[str, object], key: str, default: bool = False) -> bool:
    """The bool under ``key``, or ``default`` when absent or not a bool."""
    value = bag.get(key)
    return value if isinstance(value, bool) else default
