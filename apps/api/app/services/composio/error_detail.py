"""What Composio's API said when a call failed: status, error slug, message and request id."""

import composio_client
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

AUTH_CONFIG_NOT_FOUND_SLUG = "Auth_Config_NotFound"


class _ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str | None = None
    message: str | None = None
    request_id: str | None = None


class _ErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: _ErrorDetail


_ERROR_BODY = TypeAdapter(_ErrorBody)


class AuthConfigNotFoundError(Exception):
    """Composio has no auth config with the id this instance connects the integration through."""

    def __init__(self, integration_name: str, auth_config_id: str) -> None:
        super().__init__(
            f"{integration_name} is not set up for this Composio project: "
            f"auth config {auth_config_id} does not exist there"
        )
        self.integration_name = integration_name
        self.auth_config_id = auth_config_id


def is_auth_config_not_found(error: Exception) -> bool:
    """Report whether a Composio 404 means the auth config id is unknown to the project."""
    if not isinstance(error, composio_client.NotFoundError):
        return False
    return AUTH_CONFIG_NOT_FOUND_SLUG in str(error) or (
        _body_detail(error).slug == AUTH_CONFIG_NOT_FOUND_SLUG
    )


def composio_error_fields(error: Exception) -> dict[str, object]:
    """Log fields for a failed call: type and text, plus Composio's status, slug and request id."""
    fields: dict[str, object] = {"error": str(error), "error_type": type(error).__name__}
    if isinstance(error, composio_client.APIStatusError):
        detail = _body_detail(error)
        fields["composio_status"] = error.status_code
        fields["composio_error_slug"] = detail.slug
        fields["composio_request_id"] = detail.request_id or error.response.headers.get(
            "x-request-id"
        )
    return fields


def _body_detail(error: composio_client.APIError) -> _ErrorDetail:
    try:
        return _ERROR_BODY.validate_python(error.body).error
    except ValidationError:
        return _ErrorDetail()
