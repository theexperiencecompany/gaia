from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws
from app.config.loggers import auth_logger as logger
from app.core.websocket_manager import (
    websocket_manager as connection_manager,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

router = APIRouter(prefix="/ws", tags=["WebSocket"])


@router.websocket("/connect")
async def websocket_endpoint(websocket: WebSocket):
    """
    Endpoint to establish WebSocket connection for authenticated users.
    Each user can have multiple connections (e.g., from different devices).
    """
    # Authenticate the WebSocket connection using cookies
    user = await get_current_user_ws(websocket)

    # Check if we have a valid user with a user_id
    user_id = user.get("user_id")

    if not user_id or not isinstance(user_id, str):
        logger.warning("WebSocket connection attempted with invalid user_id")
        return

    # Accept the connection now that we've verified the user
    # If client used subprotocol auth, echo back "Bearer" to complete handshake
    protocol_header = websocket.headers.get("sec-websocket-protocol", "")
    if protocol_header.startswith("Bearer, "):
        await websocket.accept(subprotocol="Bearer")
    else:
        await websocket.accept()

    # Add the connection to our manager
    connection_manager.add_connection(user_id=user_id, websocket=websocket)

    # Remove the connection when the WebSocket is closed
    try:
        while True:
            # Keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        # Handle disconnection - WebSocket is already closed, so just clean up
        connection_manager.remove_connection(user_id=user_id, websocket=websocket)
    except Exception as e:
        # Handle any other exceptions
        logger.error(f"WebSocket error for user {user_id}: {str(e)}")
        connection_manager.remove_connection(user_id=user_id, websocket=websocket)
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            # Ignore if WebSocket is already closed
            pass  # nosec B110
        raise e
