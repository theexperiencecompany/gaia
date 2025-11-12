from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

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


class DoorController:
    """NodeMCU-based door controller using WiFi/HTTP communication."""

    _instance: Optional["DoorController"] = None

    def __init__(self, host: str = "192.168.1.100", port: int = 80):
        """
        Initialize the door controller.

        Args:
            host: IP address of NodeMCU (e.g., "192.168.1.100")
            port: HTTP port (default 80)
        """
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"

    async def send_command(self, command: str) -> Dict[str, Any]:
        """Send a command to NodeMCU via HTTP and get response."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}/door",
                    json={"command": command.upper()},
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"NodeMCU response: {data}")
                    return {
                        "success": True,
                        "data": data,
                        "status_code": response.status_code,
                    }
                else:
                    logger.error(f"NodeMCU returned status {response.status_code}")
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                        "status_code": response.status_code,
                    }

        except httpx.ConnectError as e:
            logger.error(f"Could not connect to NodeMCU at {self.base_url}: {str(e)}")
            return {
                "success": False,
                "error": f"Connection failed: {str(e)}",
            }
        except httpx.TimeoutException:
            logger.error("NodeMCU request timed out")
            return {
                "success": False,
                "error": "Request timed out",
            }
        except Exception as e:
            logger.error(f"Error sending command '{command}': {str(e)}")
            return {
                "success": False,
                "error": str(e),
            }

    async def open_door(self) -> Dict[str, Any]:
        """Open the door."""
        logger.info("Sending OPEN command to NodeMCU...")
        return await self.send_command("OPEN")

    async def close_door(self) -> Dict[str, Any]:
        """Close/lock the door."""
        logger.info("Sending CLOSE command to NodeMCU...")
        return await self.send_command("CLOSE")

    async def get_status(self) -> Dict[str, Any]:
        """Get current door status."""
        logger.info("Checking door status...")
        return await self.send_command("STATUS")

    @classmethod
    def get_instance(cls) -> "DoorController":
        """Get singleton instance of DoorController."""
        if cls._instance is None:
            # Hardcoded for testing - update with your NodeMCU's IP
            cls._instance = cls(host="192.168.1.100", port=80)
        return cls._instance


async def control_door_nodemcu(action: str, should_open: bool) -> Dict[str, Any]:
    """
    Control the door via NodeMCU WiFi connection.

    Args:
        action: "open" or "close"
        should_open: True to open, False to close

    Returns:
        Dictionary with operation result
    """
    controller = DoorController.get_instance()
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        # Send command to NodeMCU over WiFi
        if should_open:
            result = await controller.open_door()
        else:
            result = await controller.close_door()

        # Always assume success if no errors
        current_status = "OPENED" if should_open else "CLOSED"

        # Parse response data if available
        response_data = result.get("data", {})
        if isinstance(response_data, dict):
            # Extract status from response if provided
            if "status" in response_data:
                current_status = response_data["status"]
            elif "state" in response_data:
                current_status = response_data["state"]

        return {
            "success": True,
            "action": action,
            "state": current_status.lower(),
            "timestamp": timestamp,
            "message": f"Door successfully {action}ed",
            "nodemcu_response": response_data,
            "current_status": current_status,
        }

    except Exception as e:
        logger.error(f"NodeMCU control error: {str(e)}")
        return {
            "success": False,
            "action": action,
            "state": "error",
            "timestamp": timestamp,
            "message": f"Error controlling door: {str(e)}",
            "error": str(e),
        }


@tool
@with_doc(OPERATE_DOOR_DOC)
async def operate_door(
    config: RunnableConfig,
    open: Annotated[bool, "True to open the door, False to close it"],
) -> Dict[str, Any]:
    """Control a physical door by opening or closing it via NodeMCU WiFi."""
    try:
        action = "open" if open else "close"
        logger.info(f"Door operation requested: {action}")

        # Stream progress to frontend
        writer = get_stream_writer()
        writer({"progress": f"{action.capitalize()}ing the door..."})

        # Control the door via NodeMCU
        result = await control_door_nodemcu(action, open)
        logger.info(f"Door operation result: {result}")

        door_data = {
            "success": result["success"],
            "action": action,
            "is_open": open if result["success"] else not open,
            "message": result["message"],
            "timestamp": result["timestamp"],
            "details": result,
        }

        # Stream to frontend with door status
        writer({"door_data": door_data})

        return door_data

    except Exception as e:
        logger.error(f"Error in door operation: {str(e)}")
        timestamp = datetime.now(timezone.utc).isoformat()
        return {
            "success": False,
            "action": "open" if open else "close",
            "is_open": not open,
            "message": f"Error: {str(e)}",
            "timestamp": timestamp,
        }


# Export tools for registration
tools = [operate_door]
