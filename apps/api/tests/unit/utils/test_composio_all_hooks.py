"""Tests for the Composio hooks auto-registration module (``all_hooks``).

``all_hooks`` has no functions of its own: its entire contract is that importing
it imports every hook submodule (gmail, reddit, slack, twitter, user_id), and
that those imports run the ``@register_*`` decorators against the global
``hook_registry``. These tests eject the module tree from ``sys.modules``,
import ``all_hooks`` fresh, and assert that contract directly — deleting any
import line from ``all_hooks.py`` turns each test red.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import importlib
import sys
from types import ModuleType
from typing import Any

import pytest

import app.utils.composio_hooks
from app.utils.composio_hooks.registry import hook_registry

_PACKAGE = "app.utils.composio_hooks"
_ALL_HOOKS = f"{_PACKAGE}.all_hooks"
_HOOK_MODULE_SHORT_NAMES = (
    "gmail_hooks",
    "reddit_hooks",
    "slack_hooks",
    "twitter_hooks",
    "user_id_hooks",
)
_HOOK_MODULES = frozenset(f"{_PACKAGE}.{name}" for name in _HOOK_MODULE_SHORT_NAMES)


def _hook_module_names(*short_names: str) -> frozenset[str]:
    """Full module paths for the given composio hook module short names."""
    return frozenset(f"{_PACKAGE}.{name}" for name in short_names)


# Which modules register hooks in each registry list. Slack registers no
# before/after hooks (schema modifier only); user_id registers only a before hook.
_BEFORE_HOOK_MODULES = _hook_module_names(
    "gmail_hooks", "reddit_hooks", "twitter_hooks", "user_id_hooks"
)
_AFTER_HOOK_MODULES = _hook_module_names("gmail_hooks", "reddit_hooks", "twitter_hooks")
_SCHEMA_MODIFIER_MODULES = _hook_module_names("gmail_hooks", "slack_hooks", "twitter_hooks")


@contextmanager
def _isolated_all_hooks_import() -> Iterator[ModuleType]:
    """Eject ``all_hooks`` + its submodules so an import runs the module fresh.

    Yields the composio hooks package. On exit, restores the previous
    ``sys.modules`` entries, package attributes, and registry lists so the test
    leaves no trace (re-importing real modules re-runs their decorators).
    """
    package = app.utils.composio_hooks
    module_names = (_ALL_HOOKS, *sorted(_HOOK_MODULES))
    saved_modules = {name: sys.modules.get(name) for name in module_names}
    saved_attrs = {name: getattr(package, name, None) for name in _HOOK_MODULE_SHORT_NAMES}
    saved_registry = (
        hook_registry._before_hooks,
        hook_registry._after_hooks,
        hook_registry._schema_modifiers,
    )
    for name in module_names:
        sys.modules.pop(name, None)
    for name in _HOOK_MODULE_SHORT_NAMES:
        if saved_attrs[name] is not None:
            delattr(package, name)
    try:
        yield package
    finally:
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name, module in saved_attrs.items():
            if module is None:
                if hasattr(package, name):
                    delattr(package, name)
            else:
                setattr(package, name, module)
        (
            hook_registry._before_hooks,
            hook_registry._after_hooks,
            hook_registry._schema_modifiers,
        ) = saved_registry


def _defining_module(hook: Callable[..., Any]) -> str:
    """Module that defined the function wrapped by a ``@register_*`` closure."""
    for cell in hook.__closure__ or ():
        if callable(cell.cell_contents):
            return cell.cell_contents.__module__
    raise AssertionError(f"no wrapped function found in {hook!r} closure")


class _BlockingImportFinder:
    """Meta-path finder that fails the import of exactly one named module."""

    def __init__(self, blocked_module: str) -> None:
        self._blocked_module = blocked_module

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: ModuleType | None = None,
    ) -> None:
        if fullname == self._blocked_module:
            raise ImportError(f"blocked import of {fullname}")


class TestComposioAllHooks:
    """Tests for the ``app.utils.composio_hooks.all_hooks`` module."""

    def test_importing_all_hooks_imports_every_hook_module(self) -> None:
        with _isolated_all_hooks_import() as package:
            module = importlib.import_module(_ALL_HOOKS)
            assert module.__name__ == _ALL_HOOKS
            for short_name in _HOOK_MODULE_SHORT_NAMES:
                full_name = f"{_PACKAGE}.{short_name}"
                assert full_name in sys.modules
                assert getattr(package, short_name) is sys.modules[full_name]

    def test_importing_all_hooks_registers_hooks_from_every_module(self) -> None:
        with _isolated_all_hooks_import():
            saved_before = hook_registry._before_hooks.copy()
            saved_after = hook_registry._after_hooks.copy()
            saved_schema = hook_registry._schema_modifiers.copy()
            importlib.import_module(_ALL_HOOKS)
            new_before = {
                _defining_module(h) for h in hook_registry._before_hooks if h not in saved_before
            }
            new_after = {
                _defining_module(h) for h in hook_registry._after_hooks if h not in saved_after
            }
            new_schema = {
                _defining_module(h)
                for h in hook_registry._schema_modifiers
                if h not in saved_schema
            }
            assert new_before == _BEFORE_HOOK_MODULES
            assert new_after == _AFTER_HOOK_MODULES
            assert new_schema == _SCHEMA_MODIFIER_MODULES

    def test_broken_hook_module_fails_import_loudly(self) -> None:
        blocked = f"{_PACKAGE}.slack_hooks"
        with _isolated_all_hooks_import():
            original_meta_path = list(sys.meta_path)
            try:
                sys.meta_path.insert(0, _BlockingImportFinder(blocked))
                with pytest.raises(ImportError, match="blocked import of"):
                    importlib.import_module(_ALL_HOOKS)
            finally:
                sys.meta_path[:] = original_meta_path
            assert blocked not in sys.modules
            assert _ALL_HOOKS not in sys.modules
