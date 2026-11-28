"""Connecting a connector: a key is stored only after its verify call proves it, with the account it names."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.models.connector_models import IdentityExtractor
from app.models.integration_models import Integration
from app.services.connectors.connect import connect_connector, extract_identity
from app.services.connectors.runner import RunOutcome
from app.services.connectors.service import CallFailure, ConnectorCallResult
from tests.factories import make_connector_doc, make_connector_spec

MODULE = "app.services.connectors.connect"
USER_ID = "507f1f77bcf86cd799439011"
CONNECTOR_ID = "c0ffee00-0000-4000-8000-000000000002"
SPEC = make_connector_spec("cli")


def _doc() -> Integration:
    return make_connector_doc(CONNECTOR_ID, USER_ID, SPEC, name="GitHub CLI")


def _result(failure: CallFailure | None, stdout: str = "") -> ConnectorCallResult:
    return ConnectorCallResult(
        outcome=RunOutcome.OK if failure is None else RunOutcome.EXIT_NONZERO,
        is_write=False,
        exit_code=0 if failure is None else 1,
        stdout=stdout,
        stderr="",
        failure=failure,
        output_capped=False,
        duration_ms=10,
    )


def test_identity_reads_a_json_path_or_a_regex_group() -> None:
    assert (
        extract_identity(IdentityExtractor(json_path="login"), '{"login":"octocat"}') == "octocat"
    )
    assert (
        extract_identity(
            IdentityExtractor(json_path="data.0.email"), '{"data":[{"email":"a@b.c"}]}'
        )
        == "a@b.c"
    )
    assert (
        extract_identity(IdentityExtractor(regex=r"Logged in as (\S+)"), "Logged in as jo") == "jo"
    )
    assert extract_identity(IdentityExtractor(json_path="login"), "not json") is None


class _Patched:
    def __init__(self, result: ConnectorCallResult) -> None:
        self.store = MagicMock()
        self.store.store_bearer_token = AsyncMock()
        self.save_accounts = AsyncMock()
        self.publish_connected = AsyncMock()
        self.patches = [
            patch(f"{MODULE}.load_connector", AsyncMock(return_value=(_doc(), SPEC))),
            patch(f"{MODULE}.run_with_secret", AsyncMock(return_value=result)),
            patch(f"{MODULE}.MCPTokenStore", MagicMock(return_value=self.store)),
            patch(f"{MODULE}.save_accounts", self.save_accounts),
            patch(f"{MODULE}.publish_connected", self.publish_connected),
            patch(f"{MODULE}.invalidate_user_integration_caches", AsyncMock()),
            patch(f"{MODULE}.integration_repository", MagicMock(update=AsyncMock())),
            patch(f"{MODULE}.capture"),
            patch(f"{MODULE}.log"),
        ]

    def __enter__(self) -> "_Patched":
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *_: object) -> None:
        for p in self.patches:
            p.stop()


async def test_a_verified_key_is_stored_with_the_account_it_names_and_resumes_the_task() -> None:
    with _Patched(_result(None, '{"login":"octocat"}')) as patched:
        response = await connect_connector(USER_ID, CONNECTOR_ID, "  ghp_key  ")

    assert (response.status, response.account_label) == ("connected", "octocat")
    patched.store.store_bearer_token.assert_awaited_once_with(CONNECTOR_ID, "ghp_key")
    [account] = patched.save_accounts.await_args.args[2]
    assert account.label == "octocat"
    patched.publish_connected.assert_awaited_once_with(USER_ID, CONNECTOR_ID)


async def test_a_refused_key_is_never_stored_and_the_card_says_how_to_fix_it() -> None:
    with _Patched(_result(CallFailure.AUTH)) as patched:
        response = await connect_connector(USER_ID, CONNECTOR_ID, "bad")

    assert response.status == "error"
    assert "refused" in (response.error or "")
    assert "https://github.com/settings/tokens" in (response.error or "")
    patched.store.store_bearer_token.assert_not_awaited()
    patched.publish_connected.assert_not_awaited()
