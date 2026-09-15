"""What Composio hands a custom tool at call time."""

from pydantic import BaseModel, ConfigDict, ValidationError

_MISSING_USER_ID = "Missing user_id in auth_credentials"


class CustomToolAuthCredentials(BaseModel):
    """The ``auth_credentials`` bag of a Composio custom tool.

    Composio passes the connected account's state (OAuth status, ``version``, …)
    and ``composio_custom_tool_patch`` adds the trusted ``user_id``. Only the
    two keys GAIA's tools read are declared.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str = ""
    version: str | None = None

    @classmethod
    def parse(cls, auth_credentials: dict[str, object]) -> "CustomToolAuthCredentials":
        """Validate the bag; raise ValueError when it carries no usable user_id."""
        try:
            parsed = cls.model_validate(auth_credentials)
        except ValidationError as exc:
            raise ValueError(_MISSING_USER_ID) from exc
        if not parsed.user_id:
            raise ValueError(_MISSING_USER_ID)
        return parsed


class ProxyErrorMeta(BaseModel):
    """The ``meta`` of the ``AppError`` ``proxy_client`` raises for a provider non-2xx.

    ``provider_response`` is the provider's error body as Composio parsed it —
    a JSON object for most APIs, a string for the rest — so it stays ``object``
    and is only ever rendered into an error message.
    """

    model_config = ConfigDict(extra="ignore")

    provider_response: object = None
