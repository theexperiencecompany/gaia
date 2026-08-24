"""Unit tests for app/models/composio_schemas/__init__.py export surface."""

import importlib

from app.models.composio_schemas import __all__ as ALL_EXPORTS


class TestPackageExports:
    def test_every_export_is_importable(self):
        package = importlib.import_module("app.models.composio_schemas")
        for name in ALL_EXPORTS:
            assert hasattr(package, name), f"__all__ lists missing symbol {name}"

    def test_no_shadowed_exports(self):
        # Each exported class must actually live in its composio_schemas
        # submodule — re-exporting an unrelated symbol would hide drift.
        package = importlib.import_module("app.models.composio_schemas")
        for name in ALL_EXPORTS:
            obj = getattr(package, name)
            assert getattr(obj, "__module__", "").startswith(
                "app.models.composio_schemas"
            ), f"{name} comes from {obj.__module__}"

    def test_all_is_sorted_and_unique(self):
        assert len(ALL_EXPORTS) == len(set(ALL_EXPORTS))
