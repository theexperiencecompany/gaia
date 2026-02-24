"""ComposioLangChain class definition"""

import pydantic
from composio.core.provider import AgenticProvider
from composio.utils.pydantic import parse_pydantic_error
from langchain_core.tools import StructuredTool as BaseStructuredTool


class StructuredTool(BaseStructuredTool):
    def run(self, *args, **kwargs):
        try:
            return super().run(*args, **kwargs)
        except pydantic.ValidationError as e:
            return {"successful": False, "error": parse_pydantic_error(e), "data": None}


class LangchainProvider(
    AgenticProvider[StructuredTool, list[StructuredTool]],  # type: ignore[call-arg]
    name="langchain",
):
    """
    Composio toolset for Langchain framework.
    """

    runtime = "langchain"
