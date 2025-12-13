"""
Documentation decorators for functions and methods.

This module provides decorators for applying documentation to functions.
"""


def with_doc(docstring):
    """
    Decorator that applies a docstring to a function.

    Args:
        docstring (str): The docstring to apply to the function.

    Returns:
        function: Decorator function that applies the docstring.

    Example:
        @with_doc(USER_DOC)
        def get_user(user_id: int):
            return {"id": user_id, "name": "Aryan"}
    """

    def decorator(func):
        func.__doc__ = docstring
        return func

    return decorator
