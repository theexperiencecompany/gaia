"""The LLM-facing execute proxy tool."""

from collections.abc import Mapping
import json
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.agents.tools.execute.dispatch import ToolSpace, dispatch_tool
from app.constants.execute import RAN_AS_ACCOUNT_KEY
from app.models.agent_models import AgentConfigurable, agent_configurable
from shared.py.analytics.catalog.properties import Identifier


def _for_model(output: object, account: str | None) -> str:
    """Serialise a tool result for the model, naming the account it ran as when there are several.

    A dict keeps its top-level keys (the offload marker lives there), so the account joins them.
    """
    if account is None:
        return output if isinstance(output, str) else json.dumps(output, default=str)
    if isinstance(output, dict):
        return json.dumps({RAN_AS_ACCOUNT_KEY: account, **output}, default=str)
    if isinstance(output, str):
        return f"{RAN_AS_ACCOUNT_KEY}: {account}\n{output}"
    return json.dumps({RAN_AS_ACCOUNT_KEY: account, "result": output}, default=str)


def build_execute_tool(scoped_tools: Mapping[str, BaseTool] | None = None) -> BaseTool:
    """The execute proxy, optionally confined to one agent's tool space.

    ``scoped_tools`` is a subagent's live tool dict — read at call time, so it
    reflects the whole dict however late a tool was added to it. Pass it and a
    registered tool outside that dict is refused, exactly as ``retrieve_tools``
    refuses to bind one; the executor passes nothing, because its space is the
    registry. Without this the proxy resolved every name globally and a Gmail
    subagent could run Slack's tools, leaving the retrieve_tools guard
    decorative for every integration tool.
    """

    @tool
    async def execute(
        config: RunnableConfig,
        task_description: Annotated[
            str,
            "One short user-facing line describing what this call does, e.g. "
            "'Archiving 3 promotional emails'. Shown on the tool card in the UI.",
        ],
        # Identifier-typed: a name analytics cannot carry fails the args schema before dispatch.
        tool_name: Annotated[
            Identifier,
            "Exact tool name to run, verbatim from retrieve_tools (e.g. 'GMAIL_SEND_EMAIL').",
        ],
        data: Annotated[
            dict[str, object],
            "Arguments for tool_name, matching the args schema retrieve_tools showed. "
            "Pass {} when the tool takes no arguments.",
        ],
        account: Annotated[
            str | None,
            "Which of the user's connected accounts to act as, by the name listed for "
            "the integration (e.g. 'work@acme.com'). Omit to use the primary account.",
        ] = None,
    ) -> str:
        """Run an integration tool (Gmail, GitHub, Notion, MCP, ...) by name.

        Integration tools are not called directly: discover them and read their
        args schema with retrieve_tools, then run them through execute. On an
        unknown_tool or invalid_args error, correct tool_name/data per the error
        detail and retry once. Never retry the identical call.
        """
        # UI-facing arg: consumed by the stream formatter (card label), not here.
        del task_description
        configurable: AgentConfigurable = agent_configurable(config)
        result = await dispatch_tool(
            user_id=configurable.get("user_id"),
            tool_name=tool_name,
            data=data,
            config=config,
            account=account,
            space=ToolSpace(tool_names=None if scoped_tools is None else set(scoped_tools)),
        )
        if result.error is not None:
            return json.dumps(
                {
                    "ok": False,
                    "error": result.error.kind,
                    "detail": result.error.detail,
                    "next": result.error.hint,
                }
            )
        return _for_model(result.output, result.account)

    return execute


# The unscoped proxy the global registry publishes — the executor's space is the
# whole registry, so it needs no confinement.
execute = build_execute_tool()
