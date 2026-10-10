"""Integration account factories, kept apart so suites that never touch accounts import none of their schema."""

from app.models.integration_models import (
    IntegrationAccount,
    IntegrationAccountStatus,
    UserIntegrationDocument,
    UserIntegrationStatus,
)


def provider_account_id(account_id: str) -> str:
    """Return the provider's id for a test account; never GAIA's, so mixing the two up fails."""
    return f"composio_{account_id}"


def make_integration_account(
    account_id: str,
    status: IntegrationAccountStatus = "connected",
    *,
    label: str | None = None,
    nickname: str | None = None,
    identity: dict[str, str] | None = None,
) -> IntegrationAccount:
    """Build one connected account with GAIA id account_id, labelled <account_id>@acme.com by default."""
    return IntegrationAccount(
        id=account_id,
        connected_account_id=provider_account_id(account_id),
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


def with_nickname(
    record: UserIntegrationDocument | None, account_id: str, nickname: str | None
) -> UserIntegrationDocument | None:
    """Return what set_account_nickname leaves: the record with one account renamed, or None."""
    if record is None or record.find_account(account_id) is None:
        return None
    accounts = [
        a.model_copy(update={"nickname": nickname}) if a.id == account_id else a
        for a in record.accounts
    ]
    return record.model_copy(update={"accounts": accounts})
