"""Vocabularies of the report an executor run files through finish_task."""

from enum import StrEnum


class FactKind(StrEnum):
    """What a reported fact claims, which decides how it may be worded to the user."""

    DID = "did"
    PENDING_CONFIRMATION = "pending_confirmation"
    OBSERVED = "observed"
    INFERRED = "inferred"
    NOT_DONE = "not_done"


#: Kinds that account for a successful write call: it was done, awaits confirmation, or was not.
WRITE_ACCOUNTING_KINDS = frozenset({FactKind.DID, FactKind.PENDING_CONFIRMATION, FactKind.NOT_DONE})
#: Kinds that contradict an outcome of done: a deliverable is unfinished.
UNFINISHED_KINDS = frozenset({FactKind.PENDING_CONFIRMATION, FactKind.NOT_DONE})
#: Kinds that record only what was read or concluded, so the report must say how much was read.
FINDING_KINDS = frozenset({FactKind.OBSERVED, FactKind.INFERRED})


class TimeMeaning(StrEnum):
    """What a fact's time is: when the thing happens, or the deadline it is due by."""

    HAPPENS = "happens"
    DUE_BY = "due_by"


class AnswerVerdict(StrEnum):
    """The one-word answer to an "is this true?" question."""

    TRUE = "true"
    FALSE = "false"
    MIXED = "mixed"
    UNVERIFIABLE = "unverifiable"


class NeedsYouKind(StrEnum):
    """What only the user can do to unblock a run. Approvals are reported by the approval system."""

    CHOOSE = "choose"
    PROVIDE_INFO = "provide_info"
    PROVIDE_SECRET = "provide_secret"  # nosec B105 -- a kind of ask, not a credential
    SIGN_IN = "sign_in"
    VERIFICATION_CODE = "verification_code"
    CAPTCHA = "captcha"
    EXTERNAL_REPLY = "external_reply"
    PAYMENT = "payment"


class FailureReason(StrEnum):
    """Why part or all of a run failed."""

    PROVIDER_ERROR = "provider_error"
    STEP_LIMIT = "step_limit"
    ABANDONED = "abandoned"
    CRASH = "crash"
    APPROVAL_LOST = "approval_lost"
    APPROVAL_EXPIRED = "approval_expired"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"
    SITE_BLOCKED = "site_blocked"
    ACCESS_DENIED = "access_denied"
    NOT_FOUND = "not_found"
    INTEGRATION_DISCONNECTED = "integration_disconnected"
    #: The run ended with nothing that confirms what it did, so it is not known to have worked.
    UNCONFIRMED = "unconfirmed"


class FailureRecovery(StrEnum):
    """What can be done about a failure."""

    USER_CAN_RERUN = "user_can_rerun"
    NEEDS_RECONNECT = "needs_reconnect"
    NONE = "none"
