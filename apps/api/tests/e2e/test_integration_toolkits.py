"""The four headline toolkits driven through their real tool bodies.

``test_composio_custom_tools.py`` proves *one* body reaches the provider. This
file drives the toolkits a user actually notices when they break — gmail,
googlecalendar, github, slack — and asserts the **shape** each tool returns,
because that shape is what the model reads. A tool that hands back the raw
provider payload instead of its curated view is a silent regression: nothing
raises, the agent just starts hallucinating over 40x the tokens.

Each toolkit reaches its provider through a different seam, and all three have
to be stubbed or the call goes out over the network (plan §2.8):

* **A — proxy** (gmail, most calendar tools): ``proxy_client._get_composio``.
  Everything above it is real — connected-account resolution, the toolkit →
  auth-config mapping, parameter building, the non-2xx → ``AppError``
  translation. The fake client stands in for the Composio SDK, not for GAIA.
* **B — hosted execute** (github, slack, calendar's gather-context):
  ``execute_tool``, patched **at each importing module**. Consumers do
  ``from … import execute_tool``, so patching ``context_utils.execute_tool``
  silently no-ops and the test hits the network while passing.
* **C — dispatch**: ``CustomTool.__get_auth_credentials`` runs
  ``connected_accounts.list`` before *every* invocation. Covered in depth in
  ``test_composio_custom_tools.py``; stubbed here so each test is offline.

Calendar adds a fourth seam of its own: ``CUSTOM_GET_DAY_SUMMARY`` /
``CUSTOM_FETCH_EVENTS`` go through ``app.services.calendar_service``, which
reads the user's selected-calendar preferences out of Mongo. Those functions
are patched on the ``calendar_service`` module (the tool holds a reference to
the module, not to the function, so module-level patching binds correctly);
``get_calendar_metadata_map`` is deliberately left alone where it can run for
real through seam A.

Tools run inside a **real compiled LangGraph run** rather than a bare call, so
``get_config()`` (home timezone, session id) and ``get_stream_writer()`` (the
email / calendar cards the chat UI renders) are the genuine articles.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import importlib
import json
from typing import Any, cast
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from composio import Composio
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamMode
import pytest
from typing_extensions import TypedDict

from app.config.oauth_config import get_composio_social_configs
from app.services.composio.custom_tools.registry import CustomToolsRegistry
from app.services.composio.proxy_client import invalidate_connected_account_cache
from app.utils.errors import AppError

# Imported for its side effect: app.patches installs the custom-tool schema
# patches at import time, and the contracts asserted below depend on them.
importlib.import_module("app.patches")

pytestmark = pytest.mark.e2e

USER = "user-1"
HOME_TZ = "Asia/Kolkata"
PROXY_SEAM = "app.services.composio.proxy_client._get_composio"


@pytest.fixture(scope="module")
def tools() -> dict[str, Any]:
    client = Composio(api_key="test-key-not-real")  # pragma: allowlist secret
    CustomToolsRegistry().initialize(client)
    return client.tools._custom_tools.custom_tools_registry


@pytest.fixture(autouse=True)
def _clear_connected_account_cache() -> Any:
    """The proxy caches ``connected_account_id`` for 600s in a module global.

    Without this, the second test to use a toolkit never re-resolves the
    account, so its ``connected_accounts.list`` assertions read as zero calls.
    """
    invalidate_connected_account_cache()
    yield
    invalidate_connected_account_cache()


# =============================================================================
# Harness
# =============================================================================


class _GraphState(TypedDict, total=False):
    result: Any


def run_in_graph(
    call: Any, configurable: dict[str, Any] | None = None
) -> tuple[Any, list[dict[str, Any]]]:
    """Run ``call`` inside a real compiled LangGraph run.

    Returns ``(result, streamed)`` where ``streamed`` is everything the tool
    pushed to the custom stream — the email / calendar cards the chat renders.
    A bare call would make ``get_stream_writer()`` raise and ``get_config()``
    fall back to UTC, so the timezone and card behaviour would go untested.
    """
    graph = StateGraph(_GraphState)
    graph.add_node("tool", lambda _state: {"result": call()})
    graph.add_edge(START, "tool")
    graph.add_edge("tool", END)

    streamed: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    modes: list[StreamMode] = ["custom", "values"]
    config: RunnableConfig = {"configurable": configurable or {}}
    # One cast: langgraph's overloads can't bind an empty ``total=False``
    # TypedDict to ``StateT``, and a multi-mode stream yields ``(mode, chunk)``
    # tuples its stubs type as a union. Neither changes what runs.
    parts = cast("Any", graph.compile()).stream({}, config=config, stream_mode=modes)
    for mode, chunk in parts:
        if mode == "custom":
            streamed.append(chunk)
        else:
            final = chunk
    return final["result"], streamed


def stub_auth(tool: Any, user_id: str = USER) -> Any:
    """Seam C: the per-invocation ``connected_accounts.list`` for credentials."""
    return patch.object(
        tool,
        "_CustomTool__get_auth_credentials",
        MagicMock(return_value={"user_id": user_id}),
    )


class FakeProxyResponse:
    """What ``composio.tools.proxy`` hands back: provider status, body, headers."""

    def __init__(self, data: Any, status: int = 200, headers: dict[str, Any] | None = None) -> None:
        self.status = status
        self.data = data
        self.headers = headers or {}


def fake_composio(proxy: Any, *, account_status: str = "ACTIVE") -> MagicMock:
    """A stand-in Composio SDK client for seam A.

    Everything in ``proxy_client`` above the SDK call still runs for real.
    """
    account = MagicMock()
    account.id = "connected-account-1"
    account.status = account_status
    account.auth_config.is_disabled = False
    listing = MagicMock()
    listing.items = [account]

    client = MagicMock()
    client.connected_accounts.list.return_value = listing
    client.tools.proxy.side_effect = proxy
    return client


def query_params(proxy_kwargs: dict[str, Any]) -> dict[str, str]:
    """The query string the proxy was asked to send, as a dict."""
    return {
        p["name"]: p["value"] for p in proxy_kwargs.get("parameters", []) if p["type"] == "query"
    }


def gmail_message(message_id: str, *, body: str = "Invoice #42 is attached") -> dict[str, Any]:
    """A raw Gmail ``users.messages.get`` payload, MIME tree and all."""
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "snippet": f"snippet for {message_id}",
        "labelIds": ["INBOX", "UNREAD"],
        "internalDate": "1785000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": f"Subject {message_id}"},
                {"name": "From", "value": "billing@github.com"},
                {"name": "To", "value": "me@gaia.dev"},
                {"name": "Date", "value": "Mon, 3 Aug 2026 10:00:00 +0000"},
            ],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


# =============================================================================
# GMAIL — seam A (proxy)
# =============================================================================


class TestGmailFetchMessages:
    def test_an_inbox_comes_back_curated_not_as_raw_gmail_json(self, tools):
        """The shape is the whole product here. Gmail's own payload is a MIME
        tree with base64 bodies and 20+ envelope fields per message; handing
        that to the model burns the context window and it reads the wrong
        fields. The tool must return the projected view — and *not* the body,
        which the default field set deliberately excludes."""
        tool = tools["GMAIL_FETCH_MESSAGES"]

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            if kwargs["endpoint"].endswith("/messages"):
                return FakeProxyResponse({"messages": [{"id": "m1"}], "resultSizeEstimate": 1})
            return FakeProxyResponse(gmail_message(kwargs["endpoint"].rsplit("/", 1)[1]))

        with stub_auth(tool), patch(PROXY_SEAM, return_value=fake_composio(proxy)):
            result, streamed = run_in_graph(
                lambda: tool.invoke_trusted(user_id=USER, request_kwargs={"query": "in:inbox"})
            )

        assert set(result) == {"fetched_count", "truncated", "messages"}
        message = result["messages"][0]
        assert message == {
            "id": "m1",
            "threadId": "thread-m1",
            "from": "billing@github.com",
            "to": "me@gaia.dev",
            "subject": "Subject m1",
            "snippet": "snippet for m1",
            "time": "Mon, 03 Aug 2026 10:00:00 +0000",
            "isRead": False,
            "hasAttachment": False,
            "labels": ["INBOX", "UNREAD"],
        }
        assert streamed == [
            {
                "email_fetch_data": [
                    {
                        "from": "billing@github.com",
                        "subject": "Subject m1",
                        "time": "Mon, 03 Aug 2026 10:00:00 +0000",
                        "thread_id": "thread-m1",
                        "id": "m1",
                    }
                ],
                "resultSize": 1,
            }
        ], "the inbox card the chat renders never reached the stream"

    def test_a_timeframe_is_resolved_in_the_users_home_timezone(self, tools):
        """ "Today's email" is the single most common ask, and the process
        timezone is not the user's. Resolving ``today`` in UTC serves a user in
        IST the wrong day's mail for five and a half hours out of every
        twenty-four."""
        tool = tools["GMAIL_FETCH_MESSAGES"]
        sent: list[dict[str, str]] = []

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            if kwargs["endpoint"].endswith("/messages"):
                sent.append(query_params(kwargs))
                return FakeProxyResponse({"messages": [], "resultSizeEstimate": 0})
            raise AssertionError("no message fetch expected")

        with stub_auth(tool), patch(PROXY_SEAM, return_value=fake_composio(proxy)):
            run_in_graph(
                lambda: tool.invoke_trusted(
                    user_id=USER,
                    request_kwargs={"timeframe": "today", "query": "is:unread"},
                ),
                {"user_timezone": HOME_TZ},
            )

        today = datetime.now(ZoneInfo(HOME_TZ)).date()
        tomorrow = today + timedelta(days=1)
        expected = f"after:{today:%Y/%m/%d} before:{tomorrow:%Y/%m/%d} is:unread"
        assert sent[0]["q"] == expected

    def test_two_users_a_day_apart_are_served_different_days(self, tools):
        """The timezone-independent half of the previous test: Kiritimati
        (UTC+14) and Baker Island (UTC-12) are 26 hours apart, so their local
        dates *always* differ. A tool that resolves ``today`` against the
        server clock hands both users the identical query — which is exactly
        the bug the timezone plumbing exists to prevent, and the one an
        assertion pinned to a single zone can only catch for part of the day.
        """
        tool = tools["GMAIL_FETCH_MESSAGES"]
        sent: list[str] = []

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            sent.append(query_params(kwargs)["q"])
            return FakeProxyResponse({"messages": [], "resultSizeEstimate": 0})

        for zone in ("Pacific/Kiritimati", "Etc/GMT+12"):
            invalidate_connected_account_cache()
            with stub_auth(tool), patch(PROXY_SEAM, return_value=fake_composio(proxy)):
                run_in_graph(
                    lambda: tool.invoke_trusted(
                        user_id=USER, request_kwargs={"timeframe": "today"}
                    ),
                    {"user_timezone": zone},
                )

        assert sent[0] != sent[1]

    def test_pagination_keeps_going_past_the_first_page(self, tools):
        """Gmail returns a ``nextPageToken``, not the whole result set. Stopping
        at page one silently answers "you have 2 emails" when there are 4 —
        wrong data, no error, and the agent acts on it."""
        tool = tools["GMAIL_FETCH_MESSAGES"]
        tokens: list[str | None] = []

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            endpoint = kwargs["endpoint"]
            if endpoint.endswith("/messages"):
                token = query_params(kwargs).get("pageToken")
                tokens.append(token)
                if token is None:
                    return FakeProxyResponse(
                        {
                            "messages": [{"id": "m1"}, {"id": "m2"}],
                            "nextPageToken": "PAGE-2",
                            "resultSizeEstimate": 4,
                        }
                    )
                return FakeProxyResponse({"messages": [{"id": "m3"}, {"id": "m4"}]})
            return FakeProxyResponse(gmail_message(endpoint.rsplit("/", 1)[1]))

        with stub_auth(tool), patch(PROXY_SEAM, return_value=fake_composio(proxy)):
            result, _ = run_in_graph(
                lambda: tool.invoke_trusted(
                    user_id=USER, request_kwargs={"query": "in:inbox", "per_page": 2}
                )
            )

        assert tokens == [None, "PAGE-2"]
        assert [m["id"] for m in result["messages"]] == ["m1", "m2", "m3", "m4"]
        assert result["fetched_count"] == 4
        assert result["truncated"] is False

    def test_hitting_the_cap_is_reported_as_truncated(self, tools):
        """A capped result that claims to be complete is worse than a small
        one: the agent concludes "that's all your mail" and stops looking."""
        tool = tools["GMAIL_FETCH_MESSAGES"]

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            endpoint = kwargs["endpoint"]
            if endpoint.endswith("/messages"):
                if query_params(kwargs).get("pageToken") is None:
                    return FakeProxyResponse(
                        {
                            "messages": [{"id": "m1"}, {"id": "m2"}],
                            "nextPageToken": "PAGE-2",
                            "resultSizeEstimate": 4,
                        }
                    )
                return FakeProxyResponse({"messages": [{"id": "m3"}, {"id": "m4"}]})
            return FakeProxyResponse(gmail_message(endpoint.rsplit("/", 1)[1]))

        with stub_auth(tool), patch(PROXY_SEAM, return_value=fake_composio(proxy)):
            result, _ = run_in_graph(
                lambda: tool.invoke_trusted(
                    user_id=USER,
                    request_kwargs={"query": "in:inbox", "per_page": 2, "max_messages": 3},
                )
            )

        assert result["fetched_count"] == 3
        assert result["truncated"] is True

    def test_a_large_inbox_offloads_to_a_file_the_agent_can_actually_mine(self, tools):
        """Past 50 messages the result is written to JSONL and the model gets a
        digest plus a read plan instead of the payload.

        Two things have to hold or the feature is a trap: the file must carry
        the **body** even though the inline projection drops it (the whole
        point is ``query_json(where=body contains 'invoice')`` downstream — a
        body-less file makes that silently return nothing), and the read plan's
        chunks must cover every line exactly once (a gap means a subagent never
        reads part of the inbox and nobody notices).
        """
        tool = tools["GMAIL_FETCH_MESSAGES"]
        ids = [f"m{i}" for i in range(61)]
        written: dict[str, Any] = {}

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            endpoint = kwargs["endpoint"]
            if endpoint.endswith("/messages"):
                return FakeProxyResponse(
                    {"messages": [{"id": i} for i in ids], "resultSizeEstimate": len(ids)}
                )
            return FakeProxyResponse(gmail_message(endpoint.rsplit("/", 1)[1]))

        def fake_write(
            *, user_id: str, conversation_id: str, relative_path: str, content: str
        ) -> tuple[str, str]:
            written.update(
                user_id=user_id,
                conversation_id=conversation_id,
                relative_path=relative_path,
                content=content,
            )
            return (f"/mnt/jfs/{relative_path}", f"/workspace/{relative_path}")

        with (
            stub_auth(tool),
            patch(PROXY_SEAM, return_value=fake_composio(proxy)),
            patch(
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync",
                fake_write,
            ),
        ):
            result, streamed = run_in_graph(
                lambda: tool.invoke_trusted(user_id=USER, request_kwargs={"query": "in:inbox"}),
                {"vfs_session_id": "session-9"},
            )

        assert "messages" not in result, "the oversized payload was returned inline anyway"
        assert result["total_messages"] == 61
        assert result["offloaded_to"] == f"/workspace/{written['relative_path']}"
        assert written["conversation_id"] == "session-9"

        lines = written["content"].splitlines()
        assert len(lines) == 61
        first = json.loads(lines[0])
        assert first["body"] == "Invoice #42 is attached", (
            "the offloaded file has no body — every query_json/grep over it "
            "will silently find nothing"
        )
        assert "body" not in result["inline_preview"][0], (
            "the in-context preview is carrying bodies it was meant to project away"
        )

        plan = result["read_plan"]
        assert plan["total_lines"] == 61
        covered = [
            line
            for chunk in plan["chunks"]
            for line in range(
                chunk["read"]["offset"], chunk["read"]["offset"] + chunk["read"]["limit"]
            )
        ]
        assert covered == list(range(1, 62)), "the read plan does not cover every message once"
        assert streamed == [], "an offloaded result must not also render the inbox card"


class TestGmailMutations:
    def test_a_half_failed_bulk_mark_as_read_does_not_report_success(self, tools):
        """Gmail caps ``batchModify`` at 1000 ids, so "mark all 1500 as read"
        is two calls. If the second fails and the tool still reports a clean
        success, the user is told their inbox is cleared while 500 messages sit
        unread — and the agent has no idea to retry."""
        tool = tools["GMAIL_MARK_AS_READ"]
        calls = 0

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Gmail quota exceeded")
            return FakeProxyResponse({})

        with stub_auth(tool), patch(PROXY_SEAM, return_value=fake_composio(proxy)):
            result = tool.invoke_trusted(
                user_id=USER,
                request_kwargs={"message_ids": [f"m{i}" for i in range(1500)]},
            )

        assert result["modified_count"] == 1000
        assert result["failed_count"] == 500
        assert result["partial"] is True
        assert "quota exceeded" in result["error"]

    def test_the_first_batch_failing_outright_is_raised_not_swallowed(self, tools):
        """Nothing was modified, so there is no partial result to report — a
        ``{"modified_count": 0}`` success would tell the agent the mailbox was
        already in that state."""
        tool = tools["GMAIL_ARCHIVE_EMAIL"]

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            raise RuntimeError("Gmail is down")

        with (
            stub_auth(tool),
            patch(PROXY_SEAM, return_value=fake_composio(proxy)),
            pytest.raises(AppError, match="tools.proxy failed"),
        ):
            tool.invoke_trusted(user_id=USER, request_kwargs={"message_ids": ["m1"]})


class TestGmailConnectionErrors:
    def test_a_disconnected_gmail_tells_the_user_to_reconnect_not_to_log_in(self, tools):
        """403, never 401. The web client's axios interceptor treats 401 as
        session expiry and pops the login modal at an already-logged-in user;
        403 + ``INTEGRATION_NOT_CONNECTED`` routes to the reconnect flow."""
        tool = tools["GMAIL_GET_UNREAD_COUNT"]
        client = fake_composio(lambda **kwargs: FakeProxyResponse({}), account_status="INITIATED")

        with stub_auth(tool), patch(PROXY_SEAM, return_value=client):
            with pytest.raises(AppError) as excinfo:
                tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert excinfo.value.status_code == 403
        assert excinfo.value.meta["error_code"] == "INTEGRATION_NOT_CONNECTED"

    def test_a_rejected_token_invalidates_the_cached_account(self, tools):
        """A provider 401 means Composio's stored token was rejected and its
        refresh already failed. The connected-account id is cached for ten
        minutes, so without invalidation every retry in that window replays the
        dead account and the user's reconnect appears not to take effect."""
        from app.services.composio.proxy_client import _connected_account_cache

        tool = tools["GMAIL_GET_UNREAD_COUNT"]
        client = fake_composio(
            lambda **kwargs: FakeProxyResponse({"error": "invalid_grant"}, status=401)
        )

        with stub_auth(tool), patch(PROXY_SEAM, return_value=client):
            with pytest.raises(AppError) as excinfo:
                tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert excinfo.value.status_code == 403
        assert excinfo.value.meta["error_code"] == "INTEGRATION_NOT_CONNECTED"
        assert (USER, "GMAIL") not in _connected_account_cache

    def test_the_gmail_proxy_resolves_the_gmail_auth_config(self, tools):
        """The toolkit → auth-config mapping is what ties a request to the
        right OAuth connection. Resolving the wrong one reads a different
        provider's account for this user — an integration mix-up, not an
        error."""
        tool = tools["GMAIL_GET_UNREAD_COUNT"]
        client = fake_composio(
            lambda **kwargs: FakeProxyResponse(
                {"id": "INBOX", "name": "INBOX", "messagesTotal": 120, "messagesUnread": 7}
            )
        )

        with stub_auth(tool), patch(PROXY_SEAM, return_value=client):
            result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        configs = get_composio_social_configs()
        assert client.connected_accounts.list.call_args.kwargs == {
            "user_ids": [USER],
            "auth_config_ids": [configs["gmail"].auth_config_id],
            "limit": 10,
        }
        assert result["unreadCount"] == 7
        assert result["totalCount"] == 120


# =============================================================================
# GOOGLECALENDAR — calendar_service seam + seam A (proxy)
# =============================================================================


def calendar_events_response(events: list[dict[str, Any]]) -> Any:
    from app.models.calendar_models import CalendarEventsResponse

    return CalendarEventsResponse.model_validate(
        {
            "events": events,
            "selected_calendars": ["primary"],
            "has_more": False,
            "calendars_truncated": [],
        }
    )


def calendar_event(summary: str, start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "id": summary.lower(),
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "calendarId": "primary",
    }


class TestCalendarDaySummary:
    def test_the_day_is_windowed_in_the_users_timezone(self, tools):
        """ "What's on today" is a day boundary question. Computing it in the
        server's zone asks Google for the wrong 24 hours — the user's late
        meetings vanish and tomorrow's early ones appear."""
        tool = tools["GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY"]
        window: dict[str, Any] = {}
        tz = ZoneInfo(HOME_TZ)

        async def fake_get_calendar_events(**kwargs: Any) -> Any:
            window.update(kwargs)
            return calendar_events_response(
                [
                    calendar_event(
                        "Standup",
                        datetime(2026, 8, 10, 9, 0, tzinfo=tz),
                        datetime(2026, 8, 10, 9, 30, tzinfo=tz),
                    ),
                    calendar_event(
                        "Review",
                        datetime(2026, 8, 10, 23, 0, tzinfo=tz),
                        datetime(2026, 8, 10, 23, 45, tzinfo=tz),
                    ),
                ]
            )

        async def fake_user(user_id: str) -> dict[str, str]:
            return {"timezone": HOME_TZ}

        async def fake_metadata(user_id: str) -> tuple[dict[str, str], dict[str, str]]:
            return {"primary": "#0b8043"}, {"primary": "Work"}

        with (
            stub_auth(tool),
            patch("app.services.user_service.get_user_by_id", fake_user),
            patch("app.services.calendar_service.get_calendar_events", fake_get_calendar_events),
            patch("app.services.calendar_service.get_calendar_metadata_map", fake_metadata),
        ):
            result, streamed = run_in_graph(
                lambda: tool.invoke_trusted(user_id=USER, request_kwargs={"date": "2026-08-10"})
            )

        assert window["time_min"] == "2026-08-10T00:00:00+05:30"
        assert window["time_max"] == "2026-08-11T00:00:00+05:30"
        assert result["date"] == "2026-08-10"
        assert result["timezone"] == HOME_TZ
        assert result["busy_hours"] == 1.2  # 30 + 45 minutes
        assert result["events"] == [
            {
                "summary": "Standup",
                "start_time": "2026-08-10T09:00:00+05:30",
                "end_time": "2026-08-10T09:30:00+05:30",
                "calendar_name": "Work",
                "background_color": "#0b8043",
            },
            {
                "summary": "Review",
                "start_time": "2026-08-10T23:00:00+05:30",
                "end_time": "2026-08-10T23:45:00+05:30",
                "calendar_name": "Work",
                "background_color": "#0b8043",
            },
        ]
        assert streamed == [{"calendar_fetch_data": result["events"]}]

    def test_the_next_event_is_one_that_has_not_happened_yet(self, tools):
        """``next_event`` drives "what's next?" and the proactive nudges. If it
        can pick an event that already ended, the assistant reminds the user
        about the standup they just left."""
        tool = tools["GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY"]
        tz = ZoneInfo(HOME_TZ)
        now = datetime.now(tz)

        async def fake_get_calendar_events(**kwargs: Any) -> Any:
            return calendar_events_response(
                [
                    calendar_event("Past", now - timedelta(hours=2), now - timedelta(hours=1)),
                    calendar_event("Upcoming", now + timedelta(hours=1), now + timedelta(hours=2)),
                ]
            )

        async def fake_user(user_id: str) -> dict[str, str]:
            return {"timezone": HOME_TZ}

        async def fake_metadata(user_id: str) -> tuple[dict[str, str], dict[str, str]]:
            return {}, {}

        with (
            stub_auth(tool),
            patch("app.services.user_service.get_user_by_id", fake_user),
            patch("app.services.calendar_service.get_calendar_events", fake_get_calendar_events),
            patch("app.services.calendar_service.get_calendar_metadata_map", fake_metadata),
        ):
            result, _ = run_in_graph(
                lambda: tool.invoke_trusted(
                    user_id=USER, request_kwargs={"date": now.strftime("%Y-%m-%d")}
                )
            )

        assert result["next_event"] is not None
        assert result["next_event"]["summary"] == "Upcoming"


class TestCalendarGetEvent:
    def test_a_batch_where_one_event_is_missing_reports_both_halves(self, tools):
        """Regression the code carries a comment about: dropping ``errors``
        made a partly-failed batch read as a clean success, so the agent told
        the user about two events when it had only fetched one."""
        tool = tools["GOOGLECALENDAR_CUSTOM_GET_EVENT"]

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            if kwargs["endpoint"].endswith("/events/deleted-one"):
                return FakeProxyResponse({"error": {"message": "Not Found"}}, status=404)
            return FakeProxyResponse({"id": "standup", "summary": "Standup"})

        with stub_auth(tool), patch(PROXY_SEAM, return_value=fake_composio(proxy)):
            result = tool.invoke_trusted(
                user_id=USER,
                request_kwargs={
                    "events": [
                        {"event_id": "standup", "calendar_id": "primary"},
                        {"event_id": "deleted-one", "calendar_id": "primary"},
                    ]
                },
            )

        assert [e["event_id"] for e in result["events"]] == ["standup"]
        assert result["events"][0]["event"] == {"id": "standup", "summary": "Standup"}
        assert len(result["errors"]) == 1
        assert result["errors"][0]["event_id"] == "deleted-one"

    def test_a_batch_where_every_event_fails_raises(self, tools):
        """Nothing came back, so an empty-but-successful result would read as
        "you have no such events" rather than "the lookup failed"."""
        tool = tools["GOOGLECALENDAR_CUSTOM_GET_EVENT"]

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            return FakeProxyResponse({"error": {"message": "Not Found"}}, status=404)

        with (
            stub_auth(tool),
            patch(PROXY_SEAM, return_value=fake_composio(proxy)),
            pytest.raises(RuntimeError, match="Failed to get events"),
        ):
            tool.invoke_trusted(
                user_id=USER,
                request_kwargs={"events": [{"event_id": "gone", "calendar_id": "primary"}]},
            )


class TestCalendarCreateEvent:
    def test_an_unconfirmed_event_is_drafted_and_never_reaches_google(self, tools):
        """The human-in-the-loop contract. ``confirm_immediately=False`` must
        draft only: one stray write here puts a real event on someone's
        calendar (and mails every attendee) before they agreed to it."""
        tool = tools["GOOGLECALENDAR_CUSTOM_CREATE_EVENT"]
        client = fake_composio(
            lambda **kwargs: pytest.fail("a draft must not call Google Calendar")
        )

        async def fake_metadata(user_id: str) -> tuple[dict[str, str], dict[str, str]]:
            return {"primary": "#ff0000"}, {"primary": "Work"}

        with (
            stub_auth(tool),
            patch(PROXY_SEAM, return_value=client),
            patch("app.services.calendar_service.get_calendar_metadata_map", fake_metadata),
        ):
            result, streamed = run_in_graph(
                lambda: tool.invoke_trusted(
                    user_id=USER,
                    request_kwargs={
                        "confirm_immediately": False,
                        "events": [
                            {
                                "summary": "Dentist",
                                "start_datetime": "2026-08-10T09:00:00+05:30",
                                "duration_hours": 1,
                                "duration_minutes": 30,
                                "calendar_id": "primary",
                            }
                        ],
                    },
                ),
                {"user_timezone": HOME_TZ},
            )

        assert client.tools.proxy.call_count == 0
        assert result["created"] is False
        assert "NOT been added" in result["message"]
        option = result["calendar_options"][0]
        assert option["start"] == {"dateTime": "2026-08-10T09:00:00+05:30"}
        assert option["end"] == {"dateTime": "2026-08-10T10:30:00+05:30"}
        assert option["calendar_name"] == "Work"
        assert streamed == [
            {
                "calendar_options": [
                    {
                        "summary": "Dentist",
                        "description": "",
                        "is_all_day": False,
                        "calendar_id": "primary",
                        "calendar_name": "Work",
                        "background_color": "#ff0000",
                        "start": "2026-08-10T09:00:00+05:30",
                        "end": "2026-08-10T10:30:00+05:30",
                    }
                ]
            }
        ], "the confirmation card never reached the chat, so nothing can be confirmed"

    def test_a_confirmed_event_is_written_with_the_duration_the_user_asked_for(self, tools):
        """The end time is derived, not given. Getting it wrong books the wrong
        slot on a real calendar and mails the attendees about it."""
        tool = tools["GOOGLECALENDAR_CUSTOM_CREATE_EVENT"]
        posted: list[dict[str, Any]] = []

        def proxy(**kwargs: Any) -> FakeProxyResponse:
            posted.append(kwargs)
            return FakeProxyResponse(
                {"id": "created-1", "htmlLink": "https://calendar.google.com/e/created-1"}
            )

        async def fake_metadata(user_id: str) -> tuple[dict[str, str], dict[str, str]]:
            return {"primary": "#ff0000"}, {"primary": "Work"}

        with (
            stub_auth(tool),
            patch(PROXY_SEAM, return_value=fake_composio(proxy)),
            patch("app.services.calendar_service.get_calendar_metadata_map", fake_metadata),
        ):
            result, _ = run_in_graph(
                lambda: tool.invoke_trusted(
                    user_id=USER,
                    request_kwargs={
                        "confirm_immediately": True,
                        "events": [
                            {
                                "summary": "Dentist",
                                "start_datetime": "2026-08-10T09:00:00+05:30",
                                "duration_hours": 0,
                                "duration_minutes": 45,
                                "calendar_id": "primary",
                            }
                        ],
                    },
                ),
                {"user_timezone": HOME_TZ},
            )

        assert posted[0]["method"] == "POST"
        assert posted[0]["endpoint"].endswith("/calendars/primary/events")
        assert posted[0]["body"] == {
            "summary": "Dentist",
            "start": {"dateTime": "2026-08-10T09:00:00+05:30"},
            "end": {"dateTime": "2026-08-10T09:45:00+05:30"},
        }
        assert result["created"] is True
        assert result["created_events"][0]["event_id"] == "created-1"
        assert result["errors"] == []


# =============================================================================
# GITHUB — seam B (hosted execute)
# =============================================================================


class TestGithubGatherContext:
    def test_pull_requests_are_split_out_of_the_assigned_issues(self, tools):
        """GitHub's issues endpoint returns PRs *as* issues. Leaving them mixed
        in makes the assistant report "you have 4 issues" when two are pull
        requests waiting on a merge — different work, different urgency."""
        tool = tools["GITHUB_CUSTOM_GATHER_CONTEXT"]

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            if name == "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER":
                return {
                    "issues": [
                        {"number": 1, "title": "crash on save"},
                        {"number": 2, "title": "add dark mode", "pull_request": {"url": "u"}},
                    ]
                }
            if name == "GITHUB_SEARCH_GITHUB_ISSUES_AND_PULL_REQUESTS":
                return {"items": [{"number": 3, "title": "review me"}]}
            return {"notifications": [{"id": "n1"}]}

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.github_tool.execute_tool", fake_execute),
        ):
            result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert set(result) == {
            "assigned_issues",
            "assigned_prs",
            "review_requests",
            "notifications",
        }
        assert [i["number"] for i in result["assigned_issues"]] == [1]
        assert [p["number"] for p in result["assigned_prs"]] == [2]
        assert [r["number"] for r in result["review_requests"]] == [3]
        assert result["notifications"] == [{"id": "n1"}]

    def test_a_failing_review_search_still_returns_the_rest_of_the_snapshot(self, tools):
        """Review search and notifications need scopes a token may not have.
        One missing scope must not blank the whole context snapshot — the
        assigned issues are the part the user asked about."""
        tool = tools["GITHUB_CUSTOM_GATHER_CONTEXT"]

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            if name == "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER":
                return {"issues": [{"number": 1, "title": "crash on save"}]}
            raise RuntimeError("403: token is missing the notifications scope")

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.github_tool.execute_tool", fake_execute),
        ):
            result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert [i["number"] for i in result["assigned_issues"]] == [1]
        assert result["review_requests"] == []
        assert result["notifications"] == []

    def test_the_first_call_failing_is_not_swallowed(self, tools):
        """The assigned-issues call is the snapshot. If it fails and the tool
        returns empty lists, the user is told they have nothing on their plate
        when GitHub simply never answered."""
        tool = tools["GITHUB_CUSTOM_GATHER_CONTEXT"]

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            raise RuntimeError("GitHub 502")

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.github_tool.execute_tool", fake_execute),
            pytest.raises(RuntimeError, match="GitHub 502"),
        ):
            tool.invoke_trusted(user_id=USER, request_kwargs={})

    def test_every_github_call_carries_the_invoking_user(self, tools):
        """One call threaded with the wrong (or no) user reads another
        account's issues into this user's snapshot."""
        tool = tools["GITHUB_CUSTOM_GATHER_CONTEXT"]
        users: list[str] = []

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            users.append(user_id)
            return {"issues": [], "items": [], "notifications": []}

        with (
            stub_auth(tool, user_id="user-42"),
            patch("app.agents.tools.integrations.github_tool.execute_tool", fake_execute),
        ):
            tool.invoke_trusted(user_id="user-42", request_kwargs={})

        assert len(users) == 3
        assert set(users) == {"user-42"}

    def test_missing_credentials_fail_loudly(self, tools):
        """Without a user id the tool would query GitHub as nobody. Failing
        here is the difference between "reconnect GitHub" and a confusing empty
        snapshot."""
        tool = tools["GITHUB_CUSTOM_GATHER_CONTEXT"]

        with (
            patch.object(tool, "_CustomTool__get_auth_credentials", MagicMock(return_value={})),
            patch(
                "app.agents.tools.integrations.github_tool.execute_tool",
                lambda *a, **k: pytest.fail("the body ran without a user id"),
            ),
            pytest.raises(ValueError, match="Missing user_id"),
        ):
            tool.invoke_trusted(user_id=USER, request_kwargs={})


# =============================================================================
# SLACK — seam B (hosted execute)
# =============================================================================


class TestSlackGatherContext:
    def test_a_mention_is_not_also_listed_as_an_ordinary_message(self, tools):
        """Both searches hit the same day, so a message that @-mentions the
        user comes back twice. Left unde-duplicated the assistant reports the
        same message as a mention *and* as unrelated chatter."""
        tool = tools["SLACK_CUSTOM_GATHER_CONTEXT"]

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            if "@me" in params["query"]:
                return {"messages": {"matches": [{"ts": "2", "text": "hey @me"}]}}
            return {
                "messages": {
                    "matches": [
                        {"ts": "1", "text": "deploy is green"},
                        {"ts": "2", "text": "hey @me"},
                    ]
                }
            }

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.slack_tool.execute_tool", fake_execute),
        ):
            result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert set(result) == {"messages", "mentions", "unread_count"}
        assert [m["ts"] for m in result["messages"]] == ["1"]
        assert [m["ts"] for m in result["mentions"]] == ["2"]
        assert result["unread_count"] == 2

    def test_a_workspace_with_only_mentions_does_not_report_nothing_waiting(self, tools):
        """``unread_count`` counts both lists it ships beside.

        The two lists are disjoint by construction — a mention is removed from
        ``messages`` — so counting either one alone under-reports. Counting only
        the de-duplicated remainder is the worse half: a user whose entire day is
        @-mentions gets ``unread_count: 0`` next to a populated ``mentions``
        list, and the assistant tells them nothing is waiting while it is holding
        the mentions that say otherwise.
        """
        tool = tools["SLACK_CUSTOM_GATHER_CONTEXT"]
        mentions = [{"ts": str(i), "text": f"@you please look at this {i}"} for i in range(5)]

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            return {"messages": {"matches": list(mentions)}}

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.slack_tool.execute_tool", fake_execute),
        ):
            result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert result["messages"] == []
        assert len(result["mentions"]) == 5
        assert result["unread_count"] == 5

    def test_a_mention_outside_the_message_page_is_still_counted(self, tools):
        """The two searches are independent calls with different page sizes (20
        and 10), so a mention can arrive that the message search never returned.
        Counting the raw message page misses it."""
        tool = tools["SLACK_CUSTOM_GATHER_CONTEXT"]

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            if "@me" in params["query"]:
                return {"messages": {"matches": [{"ts": "99", "text": "@you, urgent"}]}}
            return {"messages": {"matches": [{"ts": "1", "text": "deploy is green"}]}}

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.slack_tool.execute_tool", fake_execute),
        ):
            result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert result["unread_count"] == 2

    def test_the_workspace_search_is_scoped_to_today(self, tools):
        """An unscoped Slack search returns the whole workspace history — the
        snapshot stops being "what happened today" and the model drowns."""
        tool = tools["SLACK_CUSTOM_GATHER_CONTEXT"]
        queries: list[str] = []

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            queries.append(params["query"])
            return {"messages": {"matches": []}}

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.slack_tool.execute_tool", fake_execute),
        ):
            tool.invoke_trusted(user_id=USER, request_kwargs={})

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert queries == [f"on:{today}", f"on:{today} @me"]

    def test_a_failing_mention_search_still_returns_the_messages(self, tools):
        """The mention search is the optional half; losing it must not blank
        the day's messages."""
        tool = tools["SLACK_CUSTOM_GATHER_CONTEXT"]

        def fake_execute(name: str, params: dict[str, Any], user_id: str, *a: Any, **k: Any):
            if "@me" in params["query"]:
                raise RuntimeError("slack ratelimited")
            return {"messages": {"matches": [{"ts": "1", "text": "deploy is green"}]}}

        with (
            stub_auth(tool),
            patch("app.agents.tools.integrations.slack_tool.execute_tool", fake_execute),
        ):
            result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert [m["ts"] for m in result["messages"]] == ["1"]
        assert result["mentions"] == []
