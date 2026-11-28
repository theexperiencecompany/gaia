"""One catalog connector as data: its id, how users know it, and its connector spec."""

from typing import Any, NamedTuple


class CatalogRow(NamedTuple):
    id: str
    name: str
    description: str
    # A ConnectorSpec as plain data; the catalog validates it at import.
    spec: dict[str, Any]
