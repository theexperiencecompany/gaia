"""Field paths in stored documents: dotted keys, with an array's elements under a [] segment."""

from collections.abc import Iterator, Mapping
from typing import Any

ARRAY_MARKER = "[]"


def walk(document: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, object]]:
    """Yield every (path, value) in a document, nested objects and array elements included."""
    for key, child in document.items():
        path = f"{prefix}{key}"
        yield path, child
        yield from _walk_child(child, path)


def _walk_child(child: object, path: str) -> Iterator[tuple[str, object]]:
    if isinstance(child, Mapping):
        yield from walk(child, f"{path}.")
    elif isinstance(child, list):
        element_path = f"{path}{ARRAY_MARKER}"
        for element in child:
            yield element_path, element
            yield from _walk_child(element, element_path)
