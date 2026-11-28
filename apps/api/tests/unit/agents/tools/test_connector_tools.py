"""run_connector called the way execute calls it: through its own LangChain args schema."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.tools.connector_tools import run_connector
from app.models.integration_models import Integration
from app.services.connectors.runner import RunOutcome
from app.services.connectors.service import ConnectorCallResult
from tests.factories import make_connector_doc, make_connector_spec

MODULE = "app.agents.tools.connector_tools"
USER_ID = "507f1f77bcf86cd799439011"
CONNECTOR_ID = "c0ffee00-0000-4000-8000-000000000003"


def _doc() -> Integration:
    return make_connector_doc(CONNECTOR_ID, USER_ID, make_connector_spec("rest"), name="Resend")


async def test_the_call_args_reach_the_runner_through_the_tool_schema() -> None:
    run = AsyncMock(
        return_value=ConnectorCallResult(
            outcome=RunOutcome.OK,
            is_write=False,
            exit_code=0,
            stdout='{"data": []}',
            stderr="",
            failure=None,
            output_capped=False,
            duration_ms=5,
        )
    )
    store = MagicMock(get_bearer_token=AsyncMock(return_value="re_key"))
    with (
        patch(
            f"{MODULE}.load_connector", AsyncMock(return_value=(_doc(), _doc().connector_config))
        ),
        patch(f"{MODULE}.MCPTokenStore", MagicMock(return_value=store)),
        patch(
            f"{MODULE}.user_integration_repository",
            MagicMock(is_connected=AsyncMock(return_value=True)),
        ),
        patch(f"{MODULE}.run_with_secret", run),
        patch(f"{MODULE}.capture"),
        patch(f"{MODULE}.log"),
    ):
        out = await run_connector.ainvoke(
            {"connector_id": CONNECTOR_ID, "argv": ["GET", "/domains"]},
            config={"configurable": {"user_id": USER_ID}},
        )

    assert '"ok": true' in out
    assert run.await_args.args[1:] == (["GET", "/domains"], "re_key")
