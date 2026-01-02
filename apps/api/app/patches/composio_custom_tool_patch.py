# Monkey patch for Composio CustomTool to inject ``user_id`` into ``auth_credentials`` via ``__call__``.

"""Patch module that overrides ``CustomTool.__call__`` to ensure the ``user_id``
provided to a custom tool is added to the ``auth_credentials`` dictionary.
"""

from composio.core.models.custom_tools import CustomTool

# Preserve the original ``__call__`` method under a distinct name to avoid shadowing warnings.
_original_custom_tool_call = CustomTool.__call__


def _patched_call(self, **kwargs):
    """Call the custom tool while ensuring ``user_id`` is present in ``auth_credentials``.

    The original ``CustomTool.__call__`` extracts ``user_id`` from ``kwargs`` and
    obtains ``auth_credentials`` via ``__get_auth_credentials``. This wrapper adds
    the ``user_id`` key to the credentials dict before invoking the wrapped tool
    function.
    """
    from pydantic import BaseModel

    def _to_dict_recursive(obj):
        """Convert Pydantic objects to dicts recursively to handle class mismatches."""
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        elif isinstance(obj, dict):
            return {k: _to_dict_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_to_dict_recursive(item) for item in obj]
        return obj

    # Extract ``user_id`` (default to ``"default"`` if not supplied).
    user_id = kwargs.pop("user_id", None) or "default"

    # Convert any Pydantic objects in kwargs to dicts to avoid class mismatch
    # between dynamically generated models (from json_schema_to_model) and
    # the original model classes (e.g., ShareRecipient from different modules)
    kwargs = _to_dict_recursive(kwargs)

    # Validate the request model.
    request = self.request_model.model_validate(kwargs)

    # If the tool is not bound to a toolkit, call the original function directly.
    if self.toolkit is None:
        return self.f(request=request)

    # Retrieve auth credentials and inject ``user_id``.
    auth_credentials = self._CustomTool__get_auth_credentials(user_id)
    auth_credentials = dict(auth_credentials)  # shallow copy to avoid mutation
    auth_credentials["user_id"] = user_id

    # Invoke the original tool function with the patched credentials.
    return self.f(
        request=request,
        execute_request=self.client.tools.proxy,
        auth_credentials=auth_credentials,
    )


# Apply the monkey‑patch.
CustomTool.__call__ = _patched_call  # type: ignore[assignment]
