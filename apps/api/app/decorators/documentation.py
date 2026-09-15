"""
Documentation decorators for functions and methods.

This module provides decorators for applying documentation to functions.
"""

from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def with_doc(docstring: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Return a decorator that sets func.__doc__ to docstring."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        func.__doc__ = docstring
        return func

    return decorator
