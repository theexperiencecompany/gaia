from typing import Annotated, Any, Dict

import httpx

from app.config.loggers import chat_logger as logger
from app.decorators import with_doc
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


OPERATE_DOOR_DOC = """Use this tool to open or close a physical door.

When to use:
- User asks to open a door
- User asks to close a door
- User asks to unlock/lock a door (interpret as open/close)

Parameters:
- open: True to open the door, False to close it

Examples:
- "open the door" → open=True
- "close the door" → open=False
- "unlock the door" → open=True
- "lock the door" → open=False"""


@tool
@with_doc(OPERATE_DOOR_DOC)
async def operate_door(
    config: RunnableConfig,
    open: Annotated[bool, "True to open the door, False to close it"],
) -> Dict[str, Any]:
    """Control a physical door by opening or closing it."""
    try:
        action = "open" if open else "close"
        logger.info(f"Door operation requested: {action}")

        # Stream progress to frontend
        writer = get_stream_writer()
        writer({"progress": f"{action.capitalize()}ing the door..."})

        # Call dummy localhost IRL endpoint
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    "http://localhost:3001/door",
                    json={"action": action, "open": open},
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Door operation successful: {result}")

                    door_data = {
                        "success": True,
                        "action": action,
                        "is_open": open,
                        "message": f"Door {action}ed successfully",
                        "timestamp": result.get("timestamp"),
                        "details": result,
                    }

                    # Stream to frontend with door status
                    writer({"door_data": door_data})

                    return door_data
                else:
                    logger.error(
                        f"Door operation failed with status {response.status_code}"
                    )
                    return {
                        "success": False,
                        "action": action,
                        "message": f"Failed to {action} door. Status: {response.status_code}",
                        "error": response.text,
                    }

            except httpx.ConnectError:
                logger.error("Failed to connect to door control endpoint")
                return {
                    "success": False,
                    "action": action,
                    "message": "Door control service is not available. Make sure the door controller is running on localhost:3001",
                }
            except httpx.TimeoutException:
                logger.error("Door operation timed out")
                return {
                    "success": False,
                    "action": action,
                    "message": f"Door operation timed out while trying to {action}",
                }

    except Exception as e:
        logger.error(f"Error in door operation: {str(e)}")
        return {
            "success": False,
            "action": "open" if open else "close",
            "message": f"Error: {str(e)}",
        }


# Export tools for registration
tools = [operate_door]
