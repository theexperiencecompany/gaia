"""Register a Prometheus collector once per process, tolerating a module imported twice."""

from collections.abc import Callable
from typing import TypeVar, cast

from prometheus_client import REGISTRY

_CollectorT = TypeVar("_CollectorT")


def register_once(name: str, factory: Callable[[], _CollectorT]) -> _CollectorT:
    """Build the collector, or return the one already registered under name.

    uvicorn --reload and some test fixtures import a metrics module twice in one
    process, and the second registration raises ValueError("Duplicated timeseries...").
    """
    try:
        return factory()
    except ValueError:
        existing = REGISTRY._names_to_collectors.get(name)
        if existing is None:
            raise
        return cast(_CollectorT, existing)
