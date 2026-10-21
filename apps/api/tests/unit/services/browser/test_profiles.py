"""Tests for the saved-login settings service (list/forget).

Pins that list_saved_logins surfaces each domain plus its provenance (source,
browser, IP) so Settings can show where a login was imported from, and that it
queries the user's own logins most-recently-used first.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.constants.browser import BROWSER_PROFILE_TTL_SECONDS
from app.models.browser_models import BrowserProfileDocument
from app.services.browser import profiles


def _doc(
    domain: str,
    *,
    user_id: str = "u1",
    updated_at: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    **provenance: str | None,
) -> BrowserProfileDocument:
    return BrowserProfileDocument(
        id="000000000000000000000000",
        user_id=user_id,
        domain=domain,
        storage_state_blob="blob",
        updated_at=updated_at,
        **provenance,
    )


class _FakeProfileRepository:
    """Applies the user filter and sort the way Mongo would, so a wrong query shows up as wrong results rather than passing against a blind mock."""

    def __init__(self, docs: list[BrowserProfileDocument]) -> None:
        self._docs = docs

    async def list_for_user(
        self,
        user_id: str,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[BrowserProfileDocument]:
        matching = [d for d in self._docs if d.user_id == user_id]
        if sort is None:
            return matching
        field, direction = sort[0]
        if direction not in (1, -1):
            raise ValueError(f"bad sort specification: direction {direction}")
        return sorted(matching, key=lambda d: getattr(d, field), reverse=direction == -1)


def _use_repo(
    monkeypatch: pytest.MonkeyPatch, docs: list[BrowserProfileDocument]
) -> _FakeProfileRepository:
    repo = _FakeProfileRepository(docs)
    monkeypatch.setattr(profiles, "browser_profile_repository", repo)
    return repo


@pytest.mark.unit
class TestListSavedLogins:
    async def test_surfaces_import_provenance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_repo(
            monkeypatch,
            [
                _doc("github.com", source="import", source_browser="Arc", source_ip="203.0.113.7"),
                _doc("example.com"),  # browsing-acquired: no provenance
            ],
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

    async def test_returns_only_the_callers_logins_most_recent_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_repo(
            monkeypatch,
            [
                _doc("old.com", updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
                _doc("newest.com", updated_at=datetime(2026, 3, 1, tzinfo=UTC)),
                _doc("middle.com", updated_at=datetime(2026, 2, 1, tzinfo=UTC)),
                _doc("someone-else.com", user_id="u2"),
            ],
        )

        result = await profiles.list_saved_logins("u1")

        assert [r.domain for r in result] == ["newest.com", "middle.com", "old.com"]

    async def test_expiry_counts_forward_from_last_use(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """expires_at, when Mongo's TTL will forget the login, is always in the future relative to updated_at."""
        last_used = datetime(2026, 1, 1, tzinfo=UTC)
        _use_repo(monkeypatch, [_doc("github.com", updated_at=last_used)])

        [login] = await profiles.list_saved_logins("u1")

        assert login.updated_at == last_used
        assert login.expires_at == last_used + timedelta(seconds=BROWSER_PROFILE_TTL_SECONDS)
        assert login.expires_at > login.updated_at
