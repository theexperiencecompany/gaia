"""
Documentation decorators for functions and methods.

This module provides decorators for applying documentation to functions.
"""

from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def with_doc(docstring: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator that applies a docstring to a function.

    Args:
        docstring (str): The docstring to apply to the function.

    Returns:
        function: Decorator function that applies the docstring.

    Example:
        @with_doc(USER_DOC)
        def get_user(user_id: int):
            return {"id": user_id, "name": "Sam"}
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        func.__doc__ = docstring
        return func

    return decorator
