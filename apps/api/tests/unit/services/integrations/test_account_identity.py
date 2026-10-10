"""Who a connected account is (its profile call) and the label it goes by."""

from collections.abc import Iterator
import json
from unittest.mock import MagicMock, call, patch

import pytest

from app.config.oauth_config import get_integration_by_id
from app.models.oauth_models import OAuthIntegration
from app.services.integrations.account_identity import account_label, fetch_account_identity

MODULE = "app.services.integrations.account_identity"


def _integration(integration_id: str) -> OAuthIntegration:
    integration = get_integration_by_id(integration_id)
    assert integration is not None
    return integration


@pytest.fixture
def log() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.log") as wide_event:
        yield wide_event


@pytest.fixture
def execute() -> Iterator[MagicMock]:
    service = MagicMock()
    with patch(f"{MODULE}.get_composio_service", return_value=service):
        yield service.composio.tools.execute


class TestFetchAccountIdentity:
    async def test_it_asks_as_that_account_and_extracts_the_configured_fields(
        self, execute: MagicMock, log: MagicMock
    ) -> None:
        execute.return_value = {
            "successful": True,
            "data": {"user_id": "U1", "user": "ada", "team_id": "T1", "team": "Acme"},
            "error": None,
        }

        identity = await fetch_account_identity("u1", _integration("slack"), "ca_slack")

        assert identity == {
            "user_id": "U1",
            "username": "ada",
            "team_id": "T1",
            "team_name": "Acme",
        }
        execute.assert_called_once_with(
            slug="SLACK_TEST_AUTH",
            arguments={},
            user_id="u1",
            connected_account_id="ca_slack",
            dangerously_skip_version_check=True,
        )
        log.set_ns.assert_called_once_with(
            "account_identity",
            integration_id="slack",
            fields=["team_id", "team_name", "user_id", "username"],
        )

    async def test_nested_fields_and_a_json_encoded_body_are_read(self, execute: MagicMock) -> None:
        execute.return_value = {
            "successful": True,
            "data": json.dumps({"user": {"id": "L1", "displayName": "Ada", "email": "a@b.c"}}),
            "error": None,
        }

        identity = await fetch_account_identity("u1", _integration("linear"), "ca_linear")

        assert identity == {"user_id": "L1", "username": "Ada", "email": "a@b.c"}

    async def test_a_profile_body_that_is_not_an_object_raises(self, execute: MagicMock) -> None:
        execute.return_value = {"successful": True, "data": json.dumps(["ada"]), "error": None}

        with pytest.raises(ValueError, match="^profile response is list, not an object$"):
            await fetch_account_identity("u1", _integration("slack"), "ca_slack")

    async def test_a_failed_profile_call_raises(self, execute: MagicMock) -> None:
        execute.return_value = {"successful": False, "data": None, "error": "token revoked"}

        with pytest.raises(RuntimeError, match="token revoked"):
            await fetch_account_identity("u1", _integration("gmail"), "ca_gmail")

    async def test_an_integration_without_a_profile_call_has_no_identity(
        self, execute: MagicMock
    ) -> None:
        assert await fetch_account_identity("u1", _integration("googlecalendar"), "ca_1") == {}
        execute.assert_not_called()


class TestAccountLabel:
    def test_the_template_names_the_account(self) -> None:
        identity = {"username": "ada", "team_name": "Acme", "user_id": "U1"}

        assert account_label(_integration("slack"), identity, set()) == "ada @ Acme"

    def test_a_missing_template_field_falls_back_to_a_number(self, log: MagicMock) -> None:
        assert account_label(_integration("slack"), {"username": "ada"}, set()) == "Slack account 1"
        assert log.warning.call_args_list == [
            call(
                "account_label_template_missing_field",
                integration_id="slack",
                missing="'team_name'",
            )
        ]

    def test_no_identity_numbers_the_account_without_trying_the_template(
        self, log: MagicMock
    ) -> None:
        assert account_label(_integration("slack"), {}, set()) == "Slack account 1"
        log.warning.assert_not_called()

    def test_an_integration_without_a_template_ignores_the_identity(self) -> None:
        label = account_label(_integration("googlecalendar"), {"email": "a@b.c"}, set())

        assert label == "Google Calendar account 1"

    def test_numbers_skip_labels_already_taken(self) -> None:
        taken = {"Google Calendar account 2"}

        assert account_label(_integration("googlecalendar"), {}, taken) == (
            "Google Calendar account 3"
        )
