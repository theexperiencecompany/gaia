"""The ``origins`` entry of Playwright's storage_state shape.

``playwright.sync_api`` publicly re-exports ``StorageState``/``StorageStateCookie`` but not the
nested per-origin localStorage shape (only available via its private ``_impl._api_structures``
module), so it's mirrored here rather than imported from a private path. Structurally identical
to Playwright's own (unexported) ``OriginState``/``LocalStorageEntry``.
"""

from typing import TypedDict


class LocalStorageEntry(TypedDict):
    name: str
    value: str


class OriginState(TypedDict):
    origin: str
    localStorage: list[LocalStorageEntry]
