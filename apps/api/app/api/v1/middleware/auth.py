"""
This is a simplified version of the auth middleware that avoids complex type checking issues
with the WorkOS SDK. It implements the same functionality but with a more dynamic approach.
"""

from datetime import datetime
from datetime import timezone as tz
from typing import Any, Awaitable, Callable, Dict, Optional

from app.api.v1.middleware.agent_auth import verify_agent_token
from app.config.loggers import auth_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.utils.auth_utils import authenticate_workos_session
from bson import ObjectId
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from workos import AsyncWorkOSClient


class WorkOSAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for handling WorkOS authentication sessions.

    This middleware processes authentication cookies, validates sessions,
    handles session refreshes, and stores authenticated user data in request.state.
    """

    def __init__(
        self,
        app: ASGIApp,
        workos_client: Optional[AsyncWorkOSClient] = None,
        exclude_paths: Optional[list[str]] = None,
    ):
        super().__init__(app)
        # Initialize WorkOS client or use provided one
        self.workos = workos_client or AsyncWorkOSClient(
            api_key=settings.WORKOS_API_KEY,
            client_id=settings.WORKOS_CLIENT_ID,
        )
        # Paths that don't need authentication
        self.exclude_paths = exclude_paths or [
            "/docs",
            "/redoc",
            "/openapi.json",
            "/oauth/login",
            "/oauth/workos/callback",
            "/oauth/google/callback",
            "/user/logout",
            "/health",
        ]
        # agent only paths
        self.agent_only_paths = ["/api/v1/chat-stream"]
        # Cache expiry time
        self.user_cache_expiry = 3600  # 1 hour

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process the request through the authentication middleware.

        Args:
            request: The incoming request
            call_next: Callable to process the request through the next middleware/route

        Returns:
            Response: The response from the route handler with any updated auth cookies
        """
        # Skip authentication for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Extract authentication cookies
        wos_session = request.cookies.get("wos_session")

        # Fallback to Authorization header (for mobile/API clients)
        if not wos_session:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                wos_session = auth_header.split(" ", 1)[1]

        # Initialize state
        request.state.user = None
        request.state.authenticated = False
        request.state.new_session = None

        # Process authentication if we have a session cookie
        if wos_session:
            try:
                # Authenticate and possibly refresh session
                user_info, new_session = await self._authenticate_session(wos_session)

                if user_info:
                    # Store in request state for dependency injection
                    request.state.user = user_info
                    request.state.authenticated = True

                    # If session was refreshed, store new session token
                    if new_session:
                        request.state.new_session = new_session

            except Exception as e:
                logger.error(f"Authentication middleware error: {e}")
                # Don't block request on auth failures - routes can handle this
        if (
            not request.state.authenticated
            and request.url.path in self.agent_only_paths
        ):
            auth_header = request.headers.get("Authorization")
            agent_info = None
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]
                agent_info = verify_agent_token(token)
            if agent_info:
                # fetch user from db
                user_id = agent_info["user_id"]
                # Ensure user_id is an ObjectId
                if not isinstance(user_id, ObjectId):
                    try:
                        user_id = ObjectId(user_id)
                    except Exception as e:
                        logger.error(f"Invalid user_id format: {user_id} - {e}")
                        user_data = None
                    else:
                        user_data = await users_collection.find_one({"_id": user_id})
                else:
                    user_data = await users_collection.find_one({"_id": user_id})
                if user_data:
                    request.state.user = {
                        "user_id": str(user_data.get("_id")),
                        "email": user_data.get("email"),
                        "name": user_data.get("name"),
                        "picture": user_data.get("picture"),
                        "auth_provider": "workos",
                        "impersonated": True,
                    }
                    request.state.authenticated = True

        # Process the request
        response = await call_next(request)

        # Update session cookie if session was refreshed
        if hasattr(request.state, "new_session") and request.state.new_session:
            response.set_cookie(
                key="wos_session",
                value=request.state.new_session,
                httponly=True,
                secure=settings.ENV == "production",
                samesite="lax",
                max_age=60 * 60 * 24 * 7,  # 7 days
            )

        return response

    async def _authenticate_session(
        self, wos_session: str
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Authenticate a WorkOS session and refresh if needed.

        Args:
            wos_session: WorkOS sealed session from cookie

        Returns:
            tuple: (user_info, new_session_token) - Both can be None if authentication fails

        Raises:
            Exception: On authentication failure
        """

        user_info, new_session = await authenticate_workos_session(
            session_token=wos_session, workos_client=self.workos
        )

        if user_info:  # If authentication successful, add additional processing
            try:
                # Update user's last activity
                await users_collection.update_one(
                    {"email": user_info["email"]},
                    {"$set": {"last_active_at": datetime.now(tz.utc)}},
                )

                return user_info, new_session
            except Exception as e:
                logger.error(f"Error in middleware additional processing: {e}")
                return None, new_session

        return None, new_session
