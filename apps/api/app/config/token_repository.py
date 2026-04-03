"""
Integration Token Repository

This module provides centralized management for integration OAuth tokens (Google, Slack, Notion, etc.)
using PostgreSQL via SQLAlchemy. It handles token storage, retrieval, refreshing, and updates for
third-party service integrations.

Note: User authentication via WorkOS is handled separately by the WorkOSAuthMiddleware.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from shared.py.wide_events import log
from app.config.settings import settings
from app.db.postgresql import get_db_session
from app.models.db_oauth import OAuthToken
from authlib.integrations.starlette_client import OAuth
from authlib.oauth2.rfc6749 import OAuth2Token
from fastapi import HTTPException
from sqlalchemy import select, update


class TokenRepository:
    """
    Repository for managing integration OAuth tokens in PostgreSQL.

    This class handles tokens for third-party integrations like Google, Slack, Notion, etc.
    It does NOT handle WorkOS authentication tokens, which are managed by WorkOSAuthMiddleware.
    """

    def __init__(self):
        """Initialize the token repository."""

        self.oauth = OAuth()

        # Initialize supported providers
        self._init_oauth_clients()

        log.info("Token repository initialized for managing API tokens (Google, etc.)")

    def _init_oauth_clients(self):
        """Initialize OAuth clients for all supported providers."""
        # Google OAuth client
        if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
            self.oauth.register(
                name="google",
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={
                    "scope": "openid email profile",
                    "prompt": "select_account",
                },
            )
            log.info("Google OAuth client registered")
        else:
            log.warning("Google OAuth credentials not found, client not registered")

    def _get_token_expiration(self, token_data: dict) -> datetime:
        """Get token expiration time with fallback logic."""

        # Try expires_at first
        expires_at = token_data.get("expires_at")
        if expires_at:
            try:
                return datetime.fromtimestamp(float(expires_at))
            except (ValueError, TypeError, OverflowError):
                log.warning(f"Invalid expires_at: {expires_at}")

        # Fall back to expires_in
        expires_in = token_data.get("expires_in", 3500)  # Default about 1 hour
        try:
            expires_in = float(expires_in)
            return datetime.now() + timedelta(seconds=expires_in)
        except (ValueError, TypeError):
            log.warning(f"Invalid expires_in: {expires_in}, using default")
            return datetime.now(timezone.utc) + timedelta(seconds=3600)

    async def store_token(
        self, user_id: str, provider: str, token_data: Dict[str, Any]
    ) -> OAuth2Token:
        """
        Store a new integration OAuth token in the database.

        Args:
            user_id: The ID of the user
            provider: The OAuth provider (google, slack, notion, etc.)
            token_data: The token data returned from OAuth provider

        Returns:
            OAuth2Token object with the stored token data
        """
        async with get_db_session() as session:
            # Check if a token already exists for this user and provider
            stmt = select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == provider
            )
            result = await session.execute(stmt)
            existing_token = result.scalar_one_or_none()

            # Get expiration time
            expires_at = self._get_token_expiration(token_data=token_data)

            # Extract the access and refresh tokens
            access_token_value = token_data.get("access_token")
            refresh_token_value = token_data.get("refresh_token")

            # If no new refresh token is provided and there's an existing one, keep it
            if (
                not refresh_token_value
                and existing_token
                and existing_token.refresh_token
            ):
                refresh_token_value = existing_token.refresh_token
                # Update token_data to include the preserved refresh token
                token_data["refresh_token"] = refresh_token_value

            # Store all token data as JSON for future reference/debugging
            token_json = json.dumps(token_data)

            if existing_token:
                # Update existing token
                await session.execute(
                    update(OAuthToken)
                    .where(OAuthToken.id == existing_token.id)
                    .values(
                        access_token=access_token_value,
                        refresh_token=refresh_token_value,
                        token_data=token_json,
                        expires_at=expires_at,
                        updated_at=datetime.now(),
                        scopes=token_data.get("scope", ""),
                    )
                )
            else:
                # Create new token
                new_token = OAuthToken(
                    user_id=user_id,
                    provider=provider,
                    access_token=access_token_value,
                    refresh_token=refresh_token_value,
                    token_data=token_json,
                    expires_at=expires_at,
                    scopes=token_data.get("scope", ""),
                )
                session.add(new_token)

            # Commit the changes to the database
            await session.commit()

            # Create an OAuth2Token directly from our local data
            oauth_token = OAuth2Token(
                params={
                    "access_token": access_token_value,
                    "refresh_token": refresh_token_value,
                    "token_type": token_data.get("token_type", "Bearer"),
                    "expires_at": expires_at.timestamp(),
                    "scope": token_data.get("scope", ""),
                }
            )

            return oauth_token

    async def get_token(
        self, user_id: str, provider: str, renew_if_expired: bool = False
    ) -> OAuth2Token:
        """
        Retrieve an integration token for a user and provider.

        Args:
            user_id: The ID of the user
            provider: The integration provider (google, slack, notion, etc.)
            renew_if_expired: Whether to attempt token refresh if expired

        Returns:
            OAuth2Token with the token data

        Raises:
            HTTPException: If no token is found or refresh fails when needed
        """
        async with get_db_session() as session:
            # Query the token for this specific provider
            stmt = select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == provider
            )
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                raise HTTPException(
                    status_code=401, detail=f"No {provider} token found for this user"
                )

            # Parse token data from JSON for additional fields
            token_data = json.loads(token_record.token_data)

            # Create OAuth2Token from the database record
            oauth_token = OAuth2Token(
                params={
                    "access_token": token_record.access_token,
                    "refresh_token": token_record.refresh_token,
                    "token_type": token_data.get("token_type", "Bearer"),
                    "expires_at": int(token_record.expires_at.timestamp())
                    if token_record.expires_at
                    else None,
                    "scope": token_data.get("scope", ""),
                }
            )

            # Check if token is expired
            if renew_if_expired and oauth_token.is_expired():
                # Token is expired, attempt to refresh it
                refreshed_token = await self.refresh_token(user_id, provider)
                if not refreshed_token:
                    raise HTTPException(
                        status_code=401, detail=f"Failed to refresh {provider} token"
                    )
                return refreshed_token

            return oauth_token

    async def _refresh_google_token(self, refresh_token: str) -> Optional[OAuth2Token]:
        """
        Refresh a Google OAuth token using the refresh token.

        Args:
            refresh_token: The refresh token to use

        Returns:
            A new OAuth2Token or None if refreshing failed
        """

        if not self.oauth.google:
            log.error("Google OAuth client not properly initialized")
            return None

        client = self.oauth.google
        try:
            # Prepare the refresh token request
            data = {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }

            # Make the refresh token request
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(
                    settings.GOOGLE_TOKEN_URL,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

            if response.status_code != 200:
                log.error(f"Failed to refresh token: {response.text}")
                return None

            token_data = response.json()

            # Google refresh token responses don't include the refresh token
            # Add it back to maintain the full token
            token_data["refresh_token"] = refresh_token

            # Create OAuth2Token from response
            return OAuth2Token(token_data)
        except Exception as e:
            log.error(f"Error refreshing Google token: {str(e)}")
            return None

    async def _refresh_provider_token(
        self, provider: str, refresh_token: str
    ) -> Optional[OAuth2Token]:
        """
        Dispatch token refresh to the appropriate provider-specific method.

        Args:
            provider: The OAuth provider (google, slack, notion, etc.)
            refresh_token: The refresh token to use

        Returns:
            A new OAuth2Token or None if refreshing failed
        """
        if provider == "google":
            return await self._refresh_google_token(refresh_token)
        # Add more providers as needed
        else:
            log.error(f"Provider {provider} not supported for token refresh")
            return None

    async def refresh_token(self, user_id: str, provider: str) -> Optional[OAuth2Token]:
        """
        Refresh an expired integration token.

        Args:
            user_id: The ID of the user
            provider: The integration provider (google, slack, notion, etc.)

        Returns:
            The refreshed OAuth2Token or None if it couldn't be refreshed
        """
        # Get the token record for this provider
        async with get_db_session() as session:
            stmt = select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == provider
            )
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                log.warning(
                    f"Cannot refresh token: No {provider} token found for user {user_id}"
                )
                return None

            # Check if refresh token is available
            refresh_token = token_record.refresh_token
            if not refresh_token:
                log.warning(
                    f"Cannot refresh token: No refresh token for user {user_id} and provider {provider}"
                )
                return None

            # Refresh the token using the appropriate provider handler
            try:
                log.info(f"Refreshing {provider} token for user {user_id}")
                token = await self._refresh_provider_token(provider, refresh_token)

                if not token:
                    log.error(f"Failed to refresh {provider} token for user {user_id}")
                    return None

                # Convert OAuth2Token to a dictionary we can store
                token_dict = {}

                # Extract necessary attributes safely
                token_dict["access_token"] = token.get("access_token", None)
                token_dict["token_type"] = token.get("token_type", "Bearer")
                token_dict["scope"] = token.get("scope", token_record.scopes)
                token_dict["expires_in"] = token.get("expires_in", None)
                token_dict["expires_at"] = token.get("expires_at", None)

                # Preserve the refresh token
                # If the new token has a refresh token, use it; otherwise keep the existing one
                token_dict["refresh_token"] = token.get(
                    "refresh_token", token_record.refresh_token
                )

                # Store the refreshed token using our existing store_token method
                # This will return the properly formatted OAuth2Token object directly
                # without querying the database again
                refreshed_token = await self.store_token(user_id, provider, token_dict)

                log.info(f"Successfully refreshed {provider} token for user {user_id}")

                return refreshed_token
            except Exception as e:
                log.error(f"Error refreshing {provider} token: {str(e)}")
                return None

    async def revoke_token(self, user_id: str, provider: str) -> bool:
        """
        Revoke an integration token.

        Args:
            user_id: The ID of the user
            provider: The integration provider (google, slack, notion, etc.)

        Returns:
            True if successful, False otherwise
        """

        async with get_db_session() as session:
            # Find the token for the specific provider
            stmt = select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == provider
            )
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                log.warning(
                    f"Cannot revoke token: No {provider} token found for user {user_id}"
                )
                return False

            try:
                # Delete the token record
                await session.delete(token_record)
                await session.commit()
                log.info(f"Successfully revoked {provider} token for user {user_id}")
                return True
            except Exception as e:
                log.error(f"Error revoking token: {str(e)}")
                await session.rollback()
                return False

    async def get_token_by_auth_token(
        self, access_token: str, renew_if_expired: bool = False
    ) -> Optional[OAuth2Token]:
        """
        Retrieve a token using the access token.

        Args:
            access_token: The access token to search for

        Returns:
            OAuth2Token if found, None otherwise
        """
        async with get_db_session() as session:
            stmt = select(OAuthToken).where(OAuthToken.access_token == access_token)
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                return None

            # Create OAuth2Token from the record
            oauth_token = OAuth2Token(
                params={
                    "access_token": token_record.access_token,
                    "refresh_token": token_record.refresh_token,
                    "token_type": "Bearer",  # nosec B105 - OAuth2 token type, not a password
                    "expires_at": int(token_record.expires_at.timestamp())
                    if token_record.expires_at
                    else None,
                    "scope": token_record.scopes,
                }
            )

            # Log token status for debugging
            log.debug(
                f"Token expiry status - is_expired: {oauth_token.is_expired()}, will_renew: {renew_if_expired}"
            )

            # Check if token is expired
            if renew_if_expired and oauth_token.is_expired():
                # Token is expired, attempt to refresh it
                refreshed_token = await self.refresh_token(
                    token_record.user_id, token_record.provider
                )
                if not refreshed_token:
                    raise HTTPException(
                        status_code=401,
                        detail=f"Failed to refresh {token_record.provider} token",
                    )
                return refreshed_token

            return oauth_token


# Singleton instance
token_repository = TokenRepository()
