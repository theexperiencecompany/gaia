"""Contract tests for ``app.utils.composio_hooks.all_hooks``.

The module exists purely for its import side effects: importing it pulls in
every hook module so their ``@register_*`` decorators run against the global
``hook_registry``. These tests pin exactly that contract — the import succeeds,
every hook module is re-exported, and the hooks actually land in the registry.
"""

from app.utils.composio_hooks import all_hooks
from app.utils.composio_hooks.registry import hook_registry

# Mirrors all_hooks.py's side-effect import list: when a hook module is added
# there, add it here too or these tests stop proving anything.
_HOOK_MODULES = (
    "gmail_hooks",
    "reddit_hooks",
    "slack_hooks",
    "twitter_hooks",
    "user_id_hooks",
)


def test_importing_all_hooks_reexports_every_hook_module() -> None:
    for name in _HOOK_MODULES:
        assert hasattr(all_hooks, name), f"all_hooks did not import {name}"


def test_importing_all_hooks_registers_hooks_in_the_global_registry() -> None:
    # Importing all_hooks (module-level, above) must have registered at least
    # one hook of each kind — the registry is a process-wide singleton, so any
    # prior import of these modules only adds to what we assert is non-empty.
    assert hook_registry._before_hooks
    assert hook_registry._after_hooks
    assert hook_registry._schema_modifiers
