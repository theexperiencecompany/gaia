from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws
from app.core.websocket_manager import (
    websocket_manager as connection_manager,
)
from shared.py.wide_events import log

router = APIRouter(prefix="/ws", tags=["WebSocket"])


@router.websocket("/connect")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Endpoint to establish WebSocket connection for authenticated users.
    Each user can have multiple connections (e.g., from different devices).

    WebSocketWideEventMiddleware emits the connection's wide event — one
    ``ws_connection`` line per connection lifetime, covering auth failures
    too — so this handler just calls ``log.set()`` like an HTTP handler.
    """
    # Authenticate the WebSocket connection using cookies
    user = await get_current_user_ws(websocket)

    # Check if we have a valid user with a user_id
    user_id = user.get("user_id")
    if not user_id or not isinstance(user_id, str):
        log.set(disconnect_reason="auth_failure")
        log.warning("WebSocket connection attempted with invalid user_id")
        return

    log.set(user={"id": user_id})

    # Accept the connection now that we've verified the user
    # If client used subprotocol auth, echo back "Bearer" to complete handshake
    protocol_header = websocket.headers.get("sec-websocket-protocol", "")
    if protocol_header.startswith("Bearer, "):
        auth_source = "subprotocol"
        await websocket.accept(subprotocol="Bearer")
    else:
        auth_source = "cookie"
        await websocket.accept()

    log.set(auth_source=auth_source)

    # Add the connection to our manager
    connection_manager.add_connection(user_id=user_id, websocket=websocket)

    # Remove the connection when the WebSocket is closed
    try:
        while True:
            # Keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        # Handle disconnection - WebSocket is already closed, so just clean up
        log.set(disconnect_reason="client_close")
        connection_manager.remove_connection(user_id=user_id, websocket=websocket)
    except Exception as e:
        # Handle any other exceptions
        log.set(disconnect_reason="server_error")
        log.error(
            "WebSocket error",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        connection_manager.remove_connection(user_id=user_id, websocket=websocket)
        # Ignore if WebSocket is already closed
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception as close_error:
            # Socket already dead, so a failed close is expected — record it
            # rather than swallow it silently.
            log.warning(
                "WebSocket close failed",
                error_type=type(close_error).__name__,
                error=str(close_error),
            )
        raise
