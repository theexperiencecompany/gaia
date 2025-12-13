from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.templates.docstrings.flowchart_tool_docs import (
    CREATE_FLOWCHART,
)
from app.decorators import with_doc, with_rate_limiting
from app.agents.templates.flowchart_template import FLOWCHART_PROMPT_TEMPLATE


@tool
@with_rate_limiting("flowchart_creation")
@with_doc(CREATE_FLOWCHART)
async def create_flowchart(
    config: RunnableConfig,
    description: Annotated[str, "Description of the flowchart to create"],
    direction: Annotated[
        str,
        "Direction of the flowchart (TD, LR, BT, RL)",
    ] = "TD",
):
    direction = "TD" if direction not in ["TD", "LR", "BT", "RL"] else direction

    return {
        "prompt": str(
            FLOWCHART_PROMPT_TEMPLATE.invoke(
                {"description": description, "direction": direction}
            )
        )
    }
