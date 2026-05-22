# Monkey patch for Composio CustomTool to inject ``user_id`` into ``auth_credentials`` via ``__call__``.

"""Patch module that overrides ``CustomTool.__call__`` to ensure the ``user_id``
provided to a custom tool is added to the ``auth_credentials`` dictionary.

Composio no longer returns OAuth ``access_token`` values inside
``auth_credentials``. Custom tools must route provider API requests through
``app.services.composio.proxy_client.proxy_request_sync`` (which uses
``composio.tools.proxy``) rather than reading a token from this dict.
The injected ``user_id`` is the only value tools should rely on here.
"""

from typing import Any, Union

from composio.core.models.custom_tools import CustomTool
from pydantic import BaseModel

from app.utils.errors import AppError

# Preserve the original ``__call__`` method under a distinct name to avoid shadowing warnings.
_original_custom_tool_call = CustomTool.__call__


def _to_dict_recursive(obj: Any) -> Any:
    """Convert Pydantic objects to dicts recursively to handle class mismatches.

    Dynamically-generated models (from ``json_schema_to_model``) are not
    instances of the original Pydantic class, so we normalize everything
    to plain dicts/lists/scalars before passing to the request model.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _to_dict_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dict_recursive(item) for item in obj]
    return obj


def _patched_call(self: Any, **kwargs: Any) -> Any:
    """Call the custom tool while ensuring ``user_id`` is present in ``auth_credentials``.

    Raises ``AppError`` if ``user_id`` is missing — the prior fallback to a
    ``"default"`` sentinel could route a request to whichever account
    Composio considers the project default, which is wrong for multi-tenant
    SaaS. Failing fast surfaces the bug at the call site instead.
    """
    user_id = kwargs.get("user_id")
    if not user_id:
        raise AppError(
            message="Missing user_id when invoking Composio custom tool",
            why="The CustomTool was invoked without a user_id kwarg",
            fix="Caller must pass user_id; do not rely on a default account",
            status_code=500,
            meta={"tool": getattr(self, "name", None)},
        )
    del kwargs["user_id"]

    # Normalize Pydantic objects in kwargs to plain dicts to avoid class
    # mismatch between dynamically-generated models and the original classes.
    normalized: Union[dict[str, Any], list[Any], Any] = _to_dict_recursive(kwargs)

    # Validate the request model.
    request = self.request_model.model_validate(normalized)

    # If the tool is not bound to a toolkit, call the original function directly.
    if self.toolkit is None:
        return self.f(request=request)

    # Retrieve auth credentials and inject ``user_id``.
    # NOTE: We must use name-mangled private method access here because
    # Composio's CustomTool does not expose a public API for retrieving
    # auth credentials. This is a known coupling point — if Composio
    # changes their internal implementation, this patch may need updating.
    auth_credentials = self._CustomTool__get_auth_credentials(user_id)
    auth_credentials = dict(auth_credentials)  # shallow copy to avoid mutation
    auth_credentials["user_id"] = user_id

    # Invoke the original tool function with the patched credentials.
    return self.f(
        request=request,
        execute_request=self.client.tools.proxy,
        auth_credentials=auth_credentials,
    )


# Apply the monkey-patch.
CustomTool.__call__ = _patched_call  # type: ignore[assignment]
