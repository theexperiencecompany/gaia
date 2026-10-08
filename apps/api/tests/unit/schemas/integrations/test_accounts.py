"""How one integration's stored accounts are presented to the client."""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.models.integration_models import IntegrationAccount, UserIntegrationDocument
from app.schemas.integrations.accounts import (
    IntegrationAccountsResponse,
    UpdateIntegrationAccountRequest,
)

CONNECTED_AT = datetime(2026, 10, 1, tzinfo=UTC)
EXPIRED_AT = datetime(2026, 10, 5, tzinfo=UTC)


def _record() -> UserIntegrationDocument:
    return UserIntegrationDocument(
        user_id="u1",
        integration_id="gmail",
        status="connected",
        accounts=[
            IntegrationAccount(
                connected_account_id="ca_work", label="work@acme.com", connected_at=CONNECTED_AT
            ),
            IntegrationAccount(
                connected_account_id="ca_home",
                label="me@gmail.com",
                nickname="Personal",
                status="expired",
                connected_at=CONNECTED_AT,
                expired_at=EXPIRED_AT,
            ),
        ],
        primary_account_id="ca_home",
    )


def test_only_the_primary_account_is_flagged_primary() -> None:
    response = IntegrationAccountsResponse.of("gmail", _record(), max_accounts=5)

    assert [(a.id, a.is_primary) for a in response.accounts] == [
        ("ca_work", False),
        ("ca_home", True),
    ]


def test_a_nickname_is_shown_over_the_address_without_hiding_it() -> None:
    work, home = IntegrationAccountsResponse.of("gmail", _record(), max_accounts=5).accounts

    assert (work.display_name, work.label, work.nickname) == (
        "work@acme.com",
        "work@acme.com",
        None,
    )
    assert (home.display_name, home.label, home.nickname) == (
        "Personal",
        "me@gmail.com",
        "Personal",
    )


def test_an_expired_account_carries_its_status_and_when_it_died() -> None:
    work, home = IntegrationAccountsResponse.of("gmail", _record(), max_accounts=5).accounts

    assert (work.status, work.connected_at, work.expired_at) == ("connected", CONNECTED_AT, None)
    assert (home.status, home.expired_at) == ("expired", EXPIRED_AT)


def test_an_integration_never_connected_lists_no_accounts_but_keeps_the_limit() -> None:
    response = IntegrationAccountsResponse.of("notion", None, max_accounts=5)

    assert (response.integration_id, response.accounts, response.max_accounts) == (
        "notion",
        [],
        5,
    )


def test_the_wire_shape_is_camel_case() -> None:
    body = IntegrationAccountsResponse.of("gmail", _record(), max_accounts=3).model_dump(
        mode="json", by_alias=True
    )

    assert body["integrationId"] == "gmail"
    assert body["maxAccounts"] == 3
    assert body["accounts"][1]["isPrimary"] is True
    assert body["accounts"][1]["displayName"] == "Personal"


def test_an_update_reads_camel_case_and_caps_the_nickname() -> None:
    assert UpdateIntegrationAccountRequest.model_validate({"isPrimary": True}).is_primary is True

    with pytest.raises(ValidationError):
        UpdateIntegrationAccountRequest.model_validate({"nickname": "x" * 61})
