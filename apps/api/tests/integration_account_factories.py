"""Integration account factories, kept apart so suites that never touch accounts import none of their schema."""

from app.models.integration_models import (
    IntegrationAccount,
    IntegrationAccountStatus,
    UserIntegrationDocument,
    UserIntegrationStatus,
)


def make_integration_account(
    account_id: str,
    status: IntegrationAccountStatus = "connected",
    *,
    label: str | None = None,
    nickname: str | None = None,
    identity: dict[str, str] | None = None,
) -> IntegrationAccount:
    """Build one connected account, labelled <account_id>@acme.com unless a label is given."""
    return IntegrationAccount(
        connected_account_id=account_id,
        label=label or f"{account_id}@acme.com",
        nickname=nickname,
        identity=identity or {},
        status=status,
    )


def make_integration_record(
    *accounts: IntegrationAccount,
    user_id: str,
    integration_id: str = "gmail",
    primary: str | None = "ca_1",
    status: UserIntegrationStatus = "connected",
) -> UserIntegrationDocument:
    """Build a user's integration record holding these accounts."""
    return UserIntegrationDocument(
        user_id=user_id,
        integration_id=integration_id,
        status=status,
        accounts=list(accounts),
        primary_account_id=primary,
    )
