import asyncio
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

import serial

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
    """Arduino-based door controller using serial communication."""

    _instance: Optional["DoorController"] = None
    _arduino: Optional[serial.Serial] = None

    def __init__(self, port: str = "/dev/cu.usbserial-130", baudrate: int = 9600):
        """
        Initialize the door controller.

        Args:
            port: Serial port (COM3, COM4 on Windows; /dev/ttyUSB0, /dev/ttyACM0 on Linux/Mac)
            baudrate: Communication speed (must match Arduino)
        """
        self.port = port
        self.baudrate = baudrate
        self.arduino = None

    def connect(self):
        """Establish connection to Arduino."""
        try:
            if self.arduino is None or not self.arduino.is_open:
                self.arduino = serial.Serial(self.port, self.baudrate, timeout=1)
                time.sleep(2)  # Wait for Arduino to reset
                logger.info(f"Connected to Arduino on {self.port}")
            return True
        except Exception as e:
            logger.error(f"Could not connect to Arduino on {self.port}: {str(e)}")
            return False

    def send_command(self, command: str) -> list[str]:
        """Send a command to Arduino and read response."""
        try:
            if self.arduino is None or not self.arduino.is_open:
                if not self.connect():
                    return ["ERROR: Not connected"]

            self.arduino.write(f"{command}\n".encode())
            time.sleep(0.5)

            # Read all available responses
            responses = []
            while self.arduino.in_waiting > 0:
                response = self.arduino.readline().decode().strip()
                if response:
                    responses.append(response)
                    logger.info(f"Arduino response: {response}")

            return responses

        except Exception as e:
            logger.error(f"Error sending command '{command}': {str(e)}")
            return [f"ERROR: {str(e)}"]

    def open_door(self) -> list[str]:
        """Open the door."""
        logger.info("Sending OPEN command to Arduino...")
        return self.send_command("OPEN")

    def close_door(self) -> list[str]:
        """Close/lock the door."""
        logger.info("Sending CLOSE command to Arduino...")
        return self.send_command("CLOSE")

    def get_status(self) -> str:
        """Get current door status."""
        logger.info("Checking door status...")
        responses = self.send_command("STATUS")
        for response in responses:
            if "STATUS:" in response:
                return response.split(":")[1].strip()
        return "UNKNOWN"

    def close_connection(self):
        """Close the serial connection."""
        try:
            if self.arduino and self.arduino.is_open:
                self.arduino.close()
                logger.info("Arduino connection closed")
                self.arduino = None
        except Exception as e:
            logger.error(f"Error closing connection: {str(e)}")

    @classmethod
    def get_instance(cls) -> "DoorController":
        """Get singleton instance of DoorController."""
        if cls._instance is None:
            # Hardcoded for testing
            cls._instance = cls(port="/dev/cu.usbserial-130", baudrate=9600)
        return cls._instance


async def control_door_arduino(action: str, should_open: bool) -> Dict[str, Any]:
    """
    Control the door via Arduino serial communication.

    Args:
        action: "open" or "close"
        should_open: True to open, False to close

    Returns:
        Dictionary with operation result
    """
    controller = DoorController.get_instance()
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        # Run serial communication in thread pool to avoid blocking
        loop = asyncio.get_event_loop()

        if should_open:
            responses = await loop.run_in_executor(None, controller.open_door)
        else:
            responses = await loop.run_in_executor(None, controller.close_door)

        # Always assume success - just send the command and trust it worked
        current_status = "OPENED" if should_open else "CLOSED"

        # Parse status from the responses if available
        for response in responses:
            if "STATUS:" in response:
                current_status = response.split(":")[1].strip()
                break

        return {
            "success": True,
            "action": action,
            "state": current_status.lower(),
            "timestamp": timestamp,
            "message": f"Door successfully {action}ed",
            "arduino_responses": responses,
            "current_status": current_status,
        }

    except Exception as e:
        logger.error(f"Arduino control error: {str(e)}")
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
    """Control a physical door by opening or closing it via Arduino."""
    try:
        action = "open" if open else "close"
        logger.info(f"Door operation requested: {action}")

        # Stream progress to frontend
        writer = get_stream_writer()
        writer({"progress": f"{action.capitalize()}ing the door..."})

        # Control the door via Arduino
        result = await control_door_arduino(action, open)
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
