"""The shared `connected -> expired` transition (app/services/integrations/integration_expiry.py).

Two callers run it: the Composio connection webhook (notify=True) and the
tool-execution reconciliation path (notify=False). Both need it to be a strict
no-op when there is nothing to expire, because a fabricated record or a repeat
notification is worse than doing nothing.

Pausing is the caller's job — the transition only receives the resulting titles
as ``paused_workflows``, so that is what these tests hand it.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.integration_models import UserIntegrationDocument
from app.services.integrations.integration_expiry import expire_user_integration

MODULE = "app.services.integrations.integration_expiry"

USER_ID = "507f1f77bcf86cd799439011"
INTEGRATION_ID = "notion"
# A custom MCP server the user added: a uuid4, so the OAuth catalog has no entry.
CUSTOM_MCP_ID = "2b0f0f9e-3f1e-4a63-9c31-1d2f7a5b8e40"


def _record(status: str, integration_id: str = INTEGRATION_ID) -> UserIntegrationDocument:
    return UserIntegrationDocument(
        id="rec-1",
        user_id=USER_ID,
        integration_id=integration_id,
        status=status,
        created_at=datetime.now(UTC),
    )


class _Seams:
    """Every side effect the transition owns, mocked at its own seam."""

    def __init__(self, record: UserIntegrationDocument | None) -> None:
        self._record = record

    def __enter__(self) -> "_Seams":
        self._patches = {
            "repo": patch(f"{MODULE}.user_integration_repository"),
            "status": patch(f"{MODULE}.update_user_integration_status", new_callable=AsyncMock),
            "proxy": patch(f"{MODULE}.invalidate_connected_account_cache"),
            "vfs": patch(f"{MODULE}.schedule_user_integrations_sync"),
            "ws": patch(f"{MODULE}.websocket_manager"),
            "notify": patch(f"{MODULE}.notification_service"),
        }
        self.mocks = {name: p.start() for name, p in self._patches.items()}
        self.mocks["repo"].get_for_user = AsyncMock(return_value=self._record)
        self.mocks["ws"].broadcast_to_user = AsyncMock()
        self.mocks["notify"].create_notification = AsyncMock()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in self._patches.values():
            p.stop()


class TestNoOpGuards:
    async def test_it_never_fabricates_a_record_for_an_integration_the_user_never_added(
        self,
    ) -> None:
        with _Seams(record=None) as s:
            changed = await expire_user_integration(
                USER_ID, INTEGRATION_ID, reason="revoked", trigger="webhook", notify=True
            )

        assert changed is False
        s.mocks["status"].assert_not_awaited()
        s.mocks["notify"].create_notification.assert_not_awaited()

    async def test_an_already_expired_integration_does_not_notify_again(self) -> None:
        # Composio can send several dead-status events for one dead account;
        # only the connected -> expired edge is worth telling the user about.
        with _Seams(record=_record("expired")) as s:
            changed = await expire_user_integration(
                USER_ID, INTEGRATION_ID, reason="revoked", trigger="webhook", notify=True
            )

        assert changed is False
        s.mocks["status"].assert_not_awaited()
        s.mocks["ws"].broadcast_to_user.assert_not_awaited()
        s.mocks["notify"].create_notification.assert_not_awaited()


class TestSideEffects:
    @pytest.mark.regression
    async def test_it_persists_the_status_and_drops_every_cache_that_would_serve_connected(
        self,
    ) -> None:
        with _Seams(record=_record("connected")) as s:
            changed = await expire_user_integration(
                USER_ID,
                INTEGRATION_ID,
                reason="refresh_token_revoked",
                trigger="webhook",
                notify=False,
                connected_account_id="ca_probe",
            )

        assert changed is True
        s.mocks["status"].assert_awaited_once_with(
            USER_ID,
            INTEGRATION_ID,
            "expired",
            expired_reason="refresh_token_revoked",
            connected_account_id="ca_probe",
        )
        # The in-process proxy map holds the now-revoked connected_account_id.
        s.mocks["proxy"].assert_called_once_with(USER_ID, "NOTION")
        # The workspace VFS must stop advertising the toolkit to the agent.
        s.mocks["vfs"].assert_called_once_with(USER_ID)

    async def test_an_integration_outside_the_oauth_catalog_still_transitions(self) -> None:
        # A custom MCP server has no catalog entry, so there is no Composio
        # toolkit to bust and no display name — neither may block the write that
        # stops the rest of GAIA treating the connection as usable.
        with _Seams(record=_record("connected", CUSTOM_MCP_ID)) as s:
            changed = await expire_user_integration(
                USER_ID, CUSTOM_MCP_ID, reason="revoked", trigger="webhook", notify=True
            )

        assert changed is True
        s.mocks["status"].assert_awaited_once_with(
            USER_ID,
            CUSTOM_MCP_ID,
            "expired",
            expired_reason="revoked",
            connected_account_id=None,
        )
        s.mocks["proxy"].assert_called_once_with(USER_ID, None)
        request = s.mocks["notify"].create_notification.await_args.args[0]
        assert request.content.title == f"{CUSTOM_MCP_ID} disconnected"

    async def test_notify_false_makes_no_noise_on_the_tool_execution_path(self) -> None:
        with _Seams(record=_record("connected")) as s:
            await expire_user_integration(
                USER_ID, INTEGRATION_ID, reason="revoked", trigger="tool_execution", notify=False
            )

        s.mocks["ws"].broadcast_to_user.assert_not_awaited()
        s.mocks["notify"].create_notification.assert_not_awaited()


class TestUserFacingAnnouncement:
    @pytest.mark.regression
    async def test_it_broadcasts_the_new_status_so_an_open_page_flips_without_a_refresh(
        self,
    ) -> None:
        with _Seams(record=_record("connected")) as s:
            await expire_user_integration(
                USER_ID, INTEGRATION_ID, reason="revoked", trigger="webhook", notify=True
            )

        s.mocks["ws"].broadcast_to_user.assert_awaited_once()
        message = s.mocks["ws"].broadcast_to_user.await_args.kwargs["message"]
        assert message["type"] == "integration_status_update"
        assert message["data"] == {"integration_id": INTEGRATION_ID, "status": "expired"}

    @pytest.mark.regression
    async def test_it_raises_exactly_one_reconnect_notification_deep_linked_to_the_integration(
        self,
    ) -> None:
        with _Seams(record=_record("connected")) as s:
            await expire_user_integration(
                USER_ID, INTEGRATION_ID, reason="revoked", trigger="webhook", notify=True
            )

        s.mocks["notify"].create_notification.assert_awaited_once()
        request = s.mocks["notify"].create_notification.await_args.args[0]
        assert request.user_id == USER_ID
        assert request.source.value == "integration_expired"
        assert request.metadata == {"integration_id": INTEGRATION_ID, "paused_workflows": 0}

        (action,) = request.content.actions
        assert action.type.value == "redirect"
        assert action.label == "Reconnect"
        assert action.config.redirect.url == f"/integrations?id={INTEGRATION_ID}"

    async def test_a_failed_notification_surfaces_and_leaves_the_transition_applied(self) -> None:
        # The announcement is the last step, so the status write and the cache
        # busts have already landed when it fails. Swallowing here would hide a
        # broken notification path behind a state change that really happened;
        # letting it out puts the failure on the caller's wide event (the webhook
        # runs this under spawn_logged_task) with the record left expired, which
        # a redelivery then treats as an idempotent no-op.
        with _Seams(record=_record("connected")) as s:
            s.mocks["notify"].create_notification.side_effect = RuntimeError("mongo down")

            with pytest.raises(RuntimeError, match="mongo down"):
                await expire_user_integration(
                    USER_ID, INTEGRATION_ID, reason="revoked", trigger="webhook", notify=True
                )

        s.mocks["status"].assert_awaited_once()
        s.mocks["proxy"].assert_called_once_with(USER_ID, "NOTION")
        s.mocks["vfs"].assert_called_once_with(USER_ID)
        s.mocks["ws"].broadcast_to_user.assert_awaited_once()


class TestPausedWorkflowsChangeTheAnnouncement:
    @pytest.mark.regression
    async def test_a_run_that_paused_workflows_announces_even_under_notify_false(self) -> None:
        # notify=False is the tool-execution path, where the connect card already
        # covers the reconnect ask — but it says nothing about workflows being
        # disabled, so silently stopping them would be the worse surprise.
        with _Seams(record=_record("connected")) as s:
            await expire_user_integration(
                USER_ID,
                INTEGRATION_ID,
                reason="revoked",
                trigger="tool_execution",
                notify=False,
                paused_workflows=["Morning digest", "Invoice filing"],
            )

        s.mocks["notify"].create_notification.assert_awaited_once()
        request = s.mocks["notify"].create_notification.await_args.args[0]
        assert "2 workflows are paused" in request.content.body
        assert request.metadata["paused_workflows"] == 2

    async def test_a_single_paused_workflow_is_named(self) -> None:
        with _Seams(record=_record("connected")) as s:
            await expire_user_integration(
                USER_ID,
                INTEGRATION_ID,
                reason="revoked",
                trigger="webhook",
                notify=True,
                paused_workflows=["Morning digest"],
            )

        body = s.mocks["notify"].create_notification.await_args.args[0].content.body
        assert "Morning digest" in body

    async def test_no_paused_workflows_keeps_the_plain_reconnect_copy(self) -> None:
        with _Seams(record=_record("connected")) as s:
            await expire_user_integration(
                USER_ID, INTEGRATION_ID, reason="revoked", trigger="webhook", notify=True
            )

        body = s.mocks["notify"].create_notification.await_args.args[0].content.body
        assert "workflow" not in body.lower()
