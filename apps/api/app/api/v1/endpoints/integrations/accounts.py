"""The connected accounts of one Composio integration: list, make primary, rename, remove."""

from fastapi import APIRouter, Depends

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.constants.integrations import MAX_ACCOUNTS_PER_INTEGRATION
from app.schemas.integrations.accounts import (
    IntegrationAccountsResponse,
    UpdateIntegrationAccountRequest,
)
from app.services.integrations.integration_account_lifecycle import (
    list_accounts,
    remove_account,
    update_account,
)
from shared.py.wide_events import log

router = APIRouter()


@router.get("/{integration_id}/accounts")
async def list_integration_accounts(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationAccountsResponse:
    log.set(user={"id": user_id}, integration={"id": integration_id, "action": "list_accounts"})
    record = await list_accounts(user_id, integration_id)
    response = IntegrationAccountsResponse.of(integration_id, record, MAX_ACCOUNTS_PER_INTEGRATION)
    log.set(result_count=len(response.accounts), outcome="success")
    return response


@router.patch("/{integration_id}/accounts/{account_id}")
async def update_integration_account(
    integration_id: str,
    account_id: str,
    payload: UpdateIntegrationAccountRequest,
    user_id: str = Depends(get_user_id),
) -> IntegrationAccountsResponse:
    log.set(
        user={"id": user_id},
        integration={"id": integration_id, "action": "update_account"},
        account={"id": account_id, "fields": sorted(payload.model_fields_set)},
    )
    record = await update_account(
        user_id,
        integration_id,
        account_id,
        nickname=payload.nickname,
        rename="nickname" in payload.model_fields_set,
        make_primary=bool(payload.is_primary),
    )
    log.set(outcome="success")
    return IntegrationAccountsResponse.of(integration_id, record, MAX_ACCOUNTS_PER_INTEGRATION)


@router.delete("/{integration_id}/accounts/{account_id}")
async def remove_integration_account(
    integration_id: str,
    account_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationAccountsResponse:
    log.set(
        user={"id": user_id},
        integration={"id": integration_id, "action": "remove_account"},
        account={"id": account_id},
    )
    record = await remove_account(user_id, integration_id, account_id)
    log.audit(
        "integration account removed",
        actor=user_id,
        resource=integration_id,
        account_id=account_id,
    )
    log.set(outcome="success", remaining=len(record.accounts) if record else 0)
    return IntegrationAccountsResponse.of(integration_id, record, MAX_ACCOUNTS_PER_INTEGRATION)
