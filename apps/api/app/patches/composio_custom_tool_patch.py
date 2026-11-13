# Monkey patch for Composio CustomTool to inject ``user_id`` into ``auth_credentials``.

"""Re-inject user_id into auth_credentials for Composio custom tools.

Composio 1.0.0 keeps user_id out of auth_credentials by design (a trusted,
structurally separate parameter an LLM can't smuggle into credential lookup).
GAIA's custom tools read user_id from auth_credentials to route requests
through app.services.composio.proxy_client, so this wraps the private,
name-mangled method both dispatch paths funnel through —
CustomTool.__get_auth_credentials — and re-adds user_id from the trusted SDK
parameter only.

If a future Composio bump renames or removes that method, the assert below
fails loudly at import time instead of every custom tool silently 500ing.
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
    """Return Composio's auth credentials with the trusted user_id added.

    user_id comes from the SDK's structurally-separate parameter, not from
    LLM-controlled request input, so re-adding it here does not reopen the
    credential-smuggling hole Composio closed.
    """
    auth_credentials = dict(_original_get_auth_credentials(self, user_id))
    auth_credentials["user_id"] = user_id
    return auth_credentials


# Apply the monkey-patch.
setattr(CustomTool, _PRIVATE_AUTH_METHOD, _patched_get_auth_credentials)
