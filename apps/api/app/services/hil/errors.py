"""Why a decision on an approval was refused."""

from http import HTTPStatus

from app.utils.errors import AppError
from shared.py.approvals import ApprovalOutcome


class ApprovalRequestNotFoundError(AppError):
    """Raised (410) when an approval request has expired or was already resolved."""

    def __init__(self) -> None:
        super().__init__(
            message="Approval request expired or already resolved",
            status_code=HTTPStatus.GONE,
        )


class ApprovalRequestForbiddenError(AppError):
    """Raised (403) when an approval request belongs to a different user."""

    def __init__(self) -> None:
        super().__init__(
            message="Approval request belongs to another user",
            status_code=HTTPStatus.FORBIDDEN,
        )


class ToolAlwaysAsksError(AppError):
    """Raised (422) when "always allow" is asked of a call that asks every time."""

    def __init__(self) -> None:
        super().__init__(
            message="This action always asks for approval and can't be set to always allow",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class LedgerDriftError(RuntimeError):
    """The ledger row was already settled when the log took the approval's decision."""

    def __init__(self, approval_id: str, outcome: ApprovalOutcome) -> None:
        super().__init__(
            f"ledger row {approval_id} was not pending when the log decided it {outcome}"
        )
