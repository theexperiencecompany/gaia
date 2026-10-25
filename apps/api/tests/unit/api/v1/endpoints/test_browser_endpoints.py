"""Tests for browser endpoints — logins, tasks, handoffs, live-view token."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app.api.v1.endpoints import browser as browser_ep
from shared.py.analytics import UserId
from shared.py.analytics.catalog.browser import BrowserImportTokenMinted, BrowserLoginsImported

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91cc"


class TestMintBrowserImportToken:
    async def test_owner_gets_a_token(self, monkeypatch):
        mint = AsyncMock(return_value="tok-123")
        monkeypatch.setattr(browser_ep, "mint_import_token", mint)
        resp = await browser_ep.mint_browser_import_token(USER_ID)
        assert resp.token == "tok-123"
        assert resp.expires_in_seconds > 0
        # The code authorises overwriting this user's logins — it must be minted
        # against the caller's real id, not a placeholder.
        assert mint.await_args.args[0] == USER_ID

    async def test_captures_analytics_attributed_to_the_session_user(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "mint_import_token", AsyncMock(return_value="tok-123"))
        captured = MagicMock()
        monkeypatch.setattr(browser_ep, "capture", captured)

        await browser_ep.mint_browser_import_token(USER_ID)

        distinct_id, event = captured.call_args.args
        assert distinct_id == UserId(USER_ID)
        assert event == BrowserImportTokenMinted()
        # No PII on the event — minting carries no properties at all.
        assert event.to_properties() == {}


class TestImportBrowserSessions:
    def _payload(self, token="tok", source_browser=None):
        from app.schemas.browser import BrowserImportRequest

        return BrowserImportRequest(
            token=token,
            cookies=[{"name": "s", "value": "1", "domain": ".github.com"}],
            origins=[{"origin": "https://github.com", "localStorage": []}],
            source_browser=source_browser,
        )

    def _consume(self, valid_token="tok", user_id=USER_ID):
        """Resolve only the code it was handed, the way the real single-use store does — a blanket stub would accept any token."""
        return AsyncMock(side_effect=lambda tok: user_id if tok == valid_token else None)

    def _request(self, forwarded=None, client_host="198.51.100.9"):
        from starlette.requests import Request

        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        scope = {
            "type": "http",
            "headers": headers,
            "client": (client_host, 12345) if client_host else None,
        }
        return Request(scope)

    def test_a_browser_name_analytics_cannot_carry_is_refused_before_the_import(self):
        with pytest.raises(ValidationError):
            self._payload(source_browser="Microsoft Edge")

    async def test_valid_token_imports_and_reports_hosts(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", self._consume("tok"))
        monkeypatch.setattr(browser_ep.settings, "BROWSER_PERSIST_LOGINS", True)
        imp = AsyncMock(return_value=[("github.com", 1)])
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)

        resp = await browser_ep.import_browser_sessions(
            self._payload(source_browser="Arc"),
            self._request(forwarded="203.0.113.7, 10.0.0.1"),
        )

        assert resp.host_count == 1
        assert resp.imported[0].domain == "github.com"
        # The route must hand the service a real user id from the consumed token,
        # the browser it came from, and the first-hop client IP.
        assert imp.await_args.args[0] == USER_ID
        assert imp.await_args.kwargs["source_browser"] == "Arc"
        assert imp.await_args.kwargs["source_ip"] == "203.0.113.7"

    async def test_uploaded_cookies_and_origins_reach_the_store(self, monkeypatch):
        """Drop a wrong-keyed payload silently, importing nothing."""
        monkeypatch.setattr(browser_ep, "consume_import_token", self._consume("tok"))
        monkeypatch.setattr(browser_ep.settings, "BROWSER_PERSIST_LOGINS", True)
        imp = AsyncMock(return_value=[("github.com", 1)])
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)

        await browser_ep.import_browser_sessions(self._payload(), self._request())

        state = imp.await_args.args[1]
        assert [c["name"] for c in state["cookies"]] == ["s"]
        assert [c["domain"] for c in state["cookies"]] == [".github.com"]
        assert [o["origin"] for o in state["origins"]] == ["https://github.com"]
        # Playwright's camelCase, not our snake_case field names: the stored slice
        # is fed straight back to add_cookies/localStorage, which ignores
        # http_only/same_site/local_storage and silently drops the login.
        assert set(state["cookies"][0]) == {
            "name",
            "value",
            "domain",
            "path",
            "expires",
            "httpOnly",
            "secure",
            "sameSite",
        }
        assert set(state["origins"][0]) == {"origin", "localStorage"}

    async def test_client_ip_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value=USER_ID))
        monkeypatch.setattr(browser_ep.settings, "BROWSER_PERSIST_LOGINS", True)
        imp = AsyncMock(return_value=[("github.com", 1)])
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)

        await browser_ep.import_browser_sessions(self._payload(), self._request())

        assert imp.await_args.kwargs["source_ip"] == "198.51.100.9"

    async def test_captures_analytics_attributed_to_token_owner(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value=USER_ID))
        monkeypatch.setattr(browser_ep.settings, "BROWSER_PERSIST_LOGINS", True)
        monkeypatch.setattr(
            browser_ep,
            "import_browser_profile",
            AsyncMock(return_value=[("github.com", 1), ("news.ycombinator.com", 2)]),
        )
        captured = MagicMock()
        monkeypatch.setattr(browser_ep, "capture", captured)

        await browser_ep.import_browser_sessions(
            self._payload(source_browser="Arc"), self._request()
        )

        # No session cookie here: the id must come from the consumed token, or the
        # event lands on an anonymous profile and never joins the user's funnel.
        distinct_id, event = captured.call_args.args
        assert distinct_id == UserId(USER_ID)
        assert event == BrowserLoginsImported(host_count=2, cookie_count=1, source_browser="Arc")

    async def test_no_analytics_when_token_rejected(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value=None))
        monkeypatch.setattr(browser_ep, "import_browser_profile", AsyncMock())
        captured = MagicMock()
        monkeypatch.setattr(browser_ep, "capture", captured)
        with pytest.raises(HTTPException):
            await browser_ep.import_browser_sessions(self._payload("expired"), self._request())
        captured.assert_not_called()

    async def test_bad_token_401(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value=None))
        imp = AsyncMock()
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.import_browser_sessions(self._payload("expired"), self._request())
        assert exc.value.status_code == 401
        assert exc.value.detail == "Import code invalid, expired, or already used"
        imp.assert_not_awaited()  # never touch storage on a bad code

    async def test_persistence_disabled_409(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value=USER_ID))
        monkeypatch.setattr(browser_ep.settings, "BROWSER_PERSIST_LOGINS", False)
        imp = AsyncMock()
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.import_browser_sessions(self._payload(), self._request())
        assert exc.value.status_code == 409
        assert exc.value.detail == "Browser login persistence is disabled"
        imp.assert_not_awaited()
