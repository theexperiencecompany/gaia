# Monkey patch for Composio CustomTool to inject ``user_id`` into ``auth_credentials``.

"""Patch that re-injects ``user_id`` into the ``auth_credentials`` dict that
Composio passes to custom tool functions.

Composio 1.0.0 reworked custom-tool dispatch. Tools are now invoked through
``CustomTools.execute(slug, request, user_id)`` -> ``CustomTool.invoke_trusted``,
and Composio deliberately keeps ``user_id`` OUT of ``auth_credentials`` (it is
treated as a structurally separate, trusted parameter so an LLM-controlled
``user_id`` cannot smuggle its way into credential lookup).

GAIA's custom tools read ``user_id`` from ``auth_credentials`` to route provider
requests through ``app.services.composio.proxy_client``. To restore that contract
without reintroducing the smuggling risk, we wrap the single private method that
both dispatch paths funnel through -- ``CustomTool.__get_auth_credentials(user_id)``
-- and re-add ``user_id`` from the trusted SDK parameter (never from request input).

This couples to a name-mangled private method. If a future Composio bump renames
or removes it, the assert below fails loudly at import time rather than letting
every custom tool silently 500 with "Missing user_id in auth_credentials".
"""

from composio.core.models.custom_tools import CustomTool

# Name-mangled private method: ``CustomTool.__get_auth_credentials``. Both
# ``__call__`` (default user) and ``invoke_trusted`` (real user via execute)
# funnel through it, so wrapping it covers every dispatch path.
_PRIVATE_AUTH_METHOD = "_CustomTool__get_auth_credentials"

if not hasattr(CustomTool, _PRIVATE_AUTH_METHOD):
    raise RuntimeError(
        "composio_custom_tool_patch: CustomTool no longer exposes "
        f"{_PRIVATE_AUTH_METHOD!r}. Composio's custom-tool internals changed -- "
        "the user_id injection patch must be updated to match the new dispatch "
        "path before custom tools will work."
    )

_original_get_auth_credentials = getattr(CustomTool, _PRIVATE_AUTH_METHOD)


def _patched_get_auth_credentials(self: CustomTool, user_id: str) -> dict:
    """Return Composio's auth credentials with the trusted ``user_id`` added.

    ``user_id`` comes from the SDK's structurally-separate parameter, not from
    LLM-controlled request input, so re-adding it here does not reopen the
    credential-smuggling hole Composio closed.
    """
    auth_credentials = dict(_original_get_auth_credentials(self, user_id))
    auth_credentials["user_id"] = user_id
    return auth_credentials


# Apply the monkey-patch.
setattr(CustomTool, _PRIVATE_AUTH_METHOD, _patched_get_auth_credentials)
