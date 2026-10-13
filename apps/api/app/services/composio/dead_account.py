"""Recognising a Composio connected account that no longer exists or works."""

import typing as t

import composio_client

from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.utils.errors import AppError

# Tool execution reports a dead account as error code 1810 (ActionExecute_ConnectedAccountNotFound);
# the proxy reports it as ConnectedAccount_ResourceNotFound. Either surfaces as a raised
# NotFoundError (404) or in a non-raising result, so every path gates on this one marker set.
_DEAD_ACCOUNT_ERROR_CODE = "1810"
_DEAD_ACCOUNT_ERROR_NAMES = frozenset(
    {"actionexecute_connectedaccountnotfound", "connectedaccount_resourcenotfound"}
)
_DEAD_ACCOUNT_MESSAGE_MARKERS = (
    _DEAD_ACCOUNT_ERROR_CODE,
    *_DEAD_ACCOUNT_ERROR_NAMES,
    "no active connected account",
    "no connected account",
)


class _ComposioErrorBody(t.TypedDict, total=False):
    error: object


class _ComposioErrorDetail(t.TypedDict, total=False):
    error_code: object
    code: object
    name: object
    type: object
    slug: object


class ConnectedAccountGoneError(AppError):
    """A provider call ran as a connected account Composio no longer holds."""

    def __init__(self, toolkit: str, cause: str) -> None:
        super().__init__(
            message=f"The {toolkit} connected account no longer exists",
            why="Composio has no connected account with the id this call ran as",
            fix=f"Reconnect the {toolkit} account",
            status_code=403,
            code=INTEGRATION_NOT_CONNECTED,
            public={"toolkit": toolkit},
            meta={"cause": cause},
        )


def message_mentions_dead_account(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _DEAD_ACCOUNT_MESSAGE_MARKERS)


def is_dead_account_error(error: composio_client.NotFoundError) -> bool:
    """Confirm a Composio 404 is the dead-connected-account failure, not some other 404.

    Prefers the structured error body, because a false positive here marks a
    healthy account expired; falls back to the message, which carries the same
    code and name.
    """
    body = error.body
    if isinstance(body, dict):
        error_body: _ComposioErrorBody = t.cast(_ComposioErrorBody, body)
        nested = error_body.get("error")
        raw_detail = nested if isinstance(nested, dict) else body
        if isinstance(raw_detail, dict):
            detail: _ComposioErrorDetail = t.cast(_ComposioErrorDetail, raw_detail)
            code = detail.get("error_code", detail.get("code"))
            if str(code) == _DEAD_ACCOUNT_ERROR_CODE:
                return True
            for value in (detail.get("name"), detail.get("type"), detail.get("slug")):
                if isinstance(value, str) and value.lower() in _DEAD_ACCOUNT_ERROR_NAMES:
                    return True
    return message_mentions_dead_account(str(error))
