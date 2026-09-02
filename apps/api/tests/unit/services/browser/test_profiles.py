"""Tests for the saved-login settings service (list/forget).

Pins that ``list_saved_logins`` surfaces each domain plus its provenance
(source / browser / IP) so Settings can show where a login was imported from.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.browser_models import BrowserProfileDocument
from app.services.browser import profiles


def _doc(domain: str, **provenance: str | None) -> BrowserProfileDocument:
    return BrowserProfileDocument(
        id="000000000000000000000000",
        user_id="u1",
        domain=domain,
        storage_state_blob="blob",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        **provenance,
    )


@pytest.mark.unit
class TestListSavedLogins:
    async def test_surfaces_import_provenance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        docs = [
            _doc("github.com", source="import", source_browser="Arc", source_ip="203.0.113.7"),
            _doc("example.com"),  # browsing-acquired: no provenance
        ]
        monkeypatch.setattr(
            profiles.browser_profile_repository,
            "list_for_user",
            AsyncMock(return_value=docs),
        )

        result = await profiles.list_saved_logins("u1")

        imported = next(r for r in result if r.domain == "github.com")
        assert imported.source == "import"
        assert imported.source_browser == "Arc"
        assert imported.source_ip == "203.0.113.7"

        browsed = next(r for r in result if r.domain == "example.com")
        assert browsed.source is None
        assert browsed.source_browser is None
        assert browsed.source_ip is None
