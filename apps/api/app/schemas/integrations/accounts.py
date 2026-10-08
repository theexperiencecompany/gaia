"""Request and response models for the connected accounts of one integration."""

from datetime import datetime

from pydantic import Field

from app.constants.integrations import MAX_ACCOUNT_NICKNAME_LENGTH
from app.models.integration_models import (
    IntegrationAccount,
    IntegrationAccountStatus,
    UserIntegrationDocument,
)
from app.schemas.common import ResponseModel
from app.schemas.integrations.responses import CamelModel


class IntegrationAccountResponse(ResponseModel, CamelModel):
    id: str
    label: str
    nickname: str | None = None
    display_name: str
    status: IntegrationAccountStatus
    is_primary: bool
    connected_at: datetime
    expired_at: datetime | None = None

    @classmethod
    def of(
        cls, account: IntegrationAccount, primary_id: str | None
    ) -> "IntegrationAccountResponse":
        return cls(
            id=account.connected_account_id,
            label=account.label,
            nickname=account.nickname,
            display_name=account.display_name,
            status=account.status,
            is_primary=account.connected_account_id == primary_id,
            connected_at=account.connected_at,
            expired_at=account.expired_at,
        )


class IntegrationAccountsResponse(ResponseModel, CamelModel):
    integration_id: str
    accounts: list[IntegrationAccountResponse]
    max_accounts: int

    @classmethod
    def of(
        cls, integration_id: str, record: UserIntegrationDocument | None, max_accounts: int
    ) -> "IntegrationAccountsResponse":
        accounts = record.accounts if record else []
        primary_id = record.primary_account_id if record else None
        return cls(
            integration_id=integration_id,
            accounts=[IntegrationAccountResponse.of(a, primary_id) for a in accounts],
            max_accounts=max_accounts,
        )


class UpdateIntegrationAccountRequest(CamelModel):
    """Make the account primary and/or rename it; an empty nickname clears it."""

    is_primary: bool | None = Field(default=None)
    nickname: str | None = Field(default=None, max_length=MAX_ACCOUNT_NICKNAME_LENGTH)
