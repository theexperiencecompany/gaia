"""
Integration Token Repository

This module provides centralized management for integration OAuth tokens (Google, Slack, Notion, etc.)
using PostgreSQL via SQLAlchemy. It handles token storage, retrieval, refreshing, and updates for
third-party service integrations.

Note: User authentication via WorkOS is handled separately by the WorkOSAuthMiddleware.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from app.config.loggers import token_repository_logger as logger
from app.config.settings import settings
from app.db.postgresql import get_db_session
from app.models.mcp_models import MCPAuthType, MCPCredential
from app.models.oauth_models import OAuthToken
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

        logger.info(
            "Token repository initialized for managing API tokens (Google, etc.)"
        )

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
            logger.info("Google OAuth client registered")
        else:
            logger.warning("Google OAuth credentials not found, client not registered")

    def _get_token_expiration(self, token_data: dict) -> datetime:
        """Get token expiration time with fallback logic."""

        # Try expires_at first
        expires_at = token_data.get("expires_at")
        if expires_at:
            try:
                return datetime.fromtimestamp(float(expires_at))
            except (ValueError, TypeError, OverflowError):
                logger.warning(f"Invalid expires_at: {expires_at}")

        # Fall back to expires_in
        expires_in = token_data.get("expires_in", 3500)  # Default about 1 hour
        try:
            expires_in = float(expires_in)
            return datetime.now() + timedelta(seconds=expires_in)
        except (ValueError, TypeError):
            logger.warning(f"Invalid expires_in: {expires_in}, using default")
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

    async def update_token(
        self, user_id: str, provider: str, token: Dict[str, Any]
    ) -> OAuth2Token:
        """
        Update an existing token with new data (typically after refresh).

        Args:
            user_id: The ID of the user
            provider: The OAuth provider
            token: The new token data

        Returns:
            OAuth2Token: The updated token object
        """
        return await self.store_token(user_id, provider, token)

    async def _refresh_google_token(self, refresh_token: str) -> Optional[OAuth2Token]:
        """
        Refresh a Google OAuth token using the refresh token.

        Args:
            refresh_token: The refresh token to use

        Returns:
            A new OAuth2Token or None if refreshing failed
        """

        if not self.oauth.google:
            logger.error("Google OAuth client not properly initialized")
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
                logger.error(f"Failed to refresh token: {response.text}")
                return None

            token_data = response.json()

            # Google refresh token responses don't include the refresh token
            # Add it back to maintain the full token
            token_data["refresh_token"] = refresh_token

            # Create OAuth2Token from response
            return OAuth2Token(token_data)
        except Exception as e:
            logger.error(f"Error refreshing Google token: {str(e)}")
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
            logger.error(f"Provider {provider} not supported for token refresh")
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
                logger.warning(
                    f"Cannot refresh token: No {provider} token found for user {user_id}"
                )
                return None

            # Check if refresh token is available
            refresh_token = token_record.refresh_token
            if not refresh_token:
                logger.warning(
                    f"Cannot refresh token: No refresh token for user {user_id} and provider {provider}"
                )
                return None

            # Refresh the token using the appropriate provider handler
            try:
                logger.info(f"Refreshing {provider} token for user {user_id}")
                token = await self._refresh_provider_token(provider, refresh_token)

                if not token:
                    logger.error(
                        f"Failed to refresh {provider} token for user {user_id}"
                    )
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

                logger.info(
                    f"Successfully refreshed {provider} token for user {user_id}"
                )

                return refreshed_token
            except Exception as e:
                logger.error(f"Error refreshing {provider} token: {str(e)}")
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
                logger.warning(
                    f"Cannot revoke token: No {provider} token found for user {user_id}"
                )
                return False

            try:
                # Delete the token record
                await session.delete(token_record)
                await session.commit()
                logger.info(f"Successfully revoked {provider} token for user {user_id}")
                return True
            except Exception as e:
                logger.error(f"Error revoking token: {str(e)}")
                await session.rollback()
                return False

    async def revoke_all_tokens(self, user_id: str) -> bool:
        """
        Revoke all integration tokens for a user.

        Args:
            user_id: The ID of the user

        Returns:
            True if successful, False otherwise
        """
        async with get_db_session() as session:
            # Find all tokens for this user
            stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
            result = await session.execute(stmt)
            tokens = result.scalars().all()

            if not tokens:
                logger.warning(f"No tokens found for user {user_id}")
                return True  # Consider it success if there's nothing to delete

            try:
                # Delete all token records for this user
                for token in tokens:
                    await session.delete(token)

                await session.commit()
                logger.info(f"Successfully revoked all tokens for user {user_id}")
                return True
            except Exception as e:
                logger.error(f"Error revoking all tokens: {str(e)}")
                await session.rollback()
                return False

    async def get_authorized_scopes(self, user_id: str, provider: str) -> List[str]:
        """
        Get all authorized scopes for a user and provider.

        Args:
            user_id: The ID of the user
            provider: The OAuth provider (google, slack, etc.)

        Returns:
            List of authorized scope strings
        """

        async with get_db_session() as session:
            # Query the specific provider token
            stmt = select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == provider
            )
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                logger.warning(f"No {provider} token found for user {user_id}")
                return []

            # Get scopes from the token record
            if not token_record.scopes:
                # Try to get scopes from token data
                try:
                    token_data = json.loads(token_record.token_data)
                    scope = token_data.get("scope", "")
                    if scope:
                        return scope.split()
                except Exception as e:
                    logger.error(f"Error parsing token data: {str(e)}")
                return []

            # Return scopes from the token record
            return token_record.scopes.split()

    async def list_user_tokens(self, user_id: str) -> Dict[str, Any]:
        """
        List all available tokens and their providers for a user.

        Args:
            user_id: The ID of the user

        Returns:
            Dictionary with information about the user's tokens
        """
        result = {
            "user_id": user_id,
            "available_providers": [],
            "token_count": 0,
            "tokens": [],
        }

        async with get_db_session() as session:
            # Find all tokens for this user
            stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
            query_result = await session.execute(stmt)
            tokens = query_result.scalars().all()

            # Populate token information
            providers = []
            token_details = []

            for token in tokens:
                providers.append(token.provider)

                # Get token expiration info
                expires_at_str = None
                if token.expires_at:
                    expires_at_str = token.expires_at.isoformat()

                # Add token details
                token_details.append(
                    {
                        "id": token.id,
                        "provider": token.provider,
                        "has_refresh_token": bool(token.refresh_token),
                        "expires_at": expires_at_str,
                        "scopes": token.scopes.split() if token.scopes else [],
                        "updated_at": token.updated_at.isoformat()
                        if token.updated_at
                        else None,
                    }
                )

            result["available_providers"] = providers
            result["token_count"] = len(tokens)
            result["tokens"] = token_details

        return result

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
                    "token_type": "Bearer",
                    "expires_at": int(token_record.expires_at.timestamp())
                    if token_record.expires_at
                    else None,
                    "scope": token_record.scopes,
                }
            )

            # Log token status for debugging
            logger.debug(
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

    # MCP Credential Management Methods

    async def store_mcp_credential(
        self,
        user_id: str,
        server_id: int,
        auth_type: str,
        credential_data: Dict[str, Any],
    ) -> bool:
        """
        Store MCP server credentials securely in PostgreSQL.

        Args:
            user_id: User ID
            server_id: MCP server ID
            auth_type: Type of authentication
            credential_data: Credential data to store

        Returns:
            True if successful
        """
        async with get_db_session() as session:
            # Check if credential already exists
            stmt = select(MCPCredential).where(
                MCPCredential.user_id == user_id,
                MCPCredential.server_id == server_id,
            )
            result = await session.execute(stmt)
            existing_credential = result.scalar_one_or_none()

            if existing_credential:
                # Update existing credential
                update_stmt = (
                    update(MCPCredential)
                    .where(MCPCredential.id == existing_credential.id)
                    .values(
                        auth_type=auth_type,
                        bearer_token=credential_data.get("bearer_token"),
                        oauth_access_token=credential_data.get("oauth_access_token"),
                        oauth_refresh_token=credential_data.get("oauth_refresh_token"),
                        oauth_client_id=credential_data.get("oauth_client_id"),
                        oauth_client_secret=credential_data.get("oauth_client_secret"),
                        basic_username=credential_data.get("basic_username"),
                        basic_password=credential_data.get("basic_password"),
                        custom_headers=json.dumps(credential_data.get("custom_headers"))
                        if credential_data.get("custom_headers")
                        else None,
                        expires_at=credential_data.get("expires_at"),
                        scopes=credential_data.get("scopes"),
                        updated_at=datetime.now(),
                    )
                )
                await session.execute(update_stmt)
            else:
                # Create new credential
                new_credential = MCPCredential(
                    user_id=user_id,
                    server_id=server_id,
                    auth_type=auth_type,
                    bearer_token=credential_data.get("bearer_token"),
                    oauth_access_token=credential_data.get("oauth_access_token"),
                    oauth_refresh_token=credential_data.get("oauth_refresh_token"),
                    oauth_client_id=credential_data.get("oauth_client_id"),
                    oauth_client_secret=credential_data.get("oauth_client_secret"),
                    basic_username=credential_data.get("basic_username"),
                    basic_password=credential_data.get("basic_password"),
                    custom_headers=json.dumps(credential_data.get("custom_headers"))
                    if credential_data.get("custom_headers")
                    else None,
                    expires_at=credential_data.get("expires_at"),
                    scopes=credential_data.get("scopes"),
                )
                session.add(new_credential)

            await session.commit()
            logger.info(
                f"Stored MCP credentials for user {user_id}, server {server_id}"
            )
            return True

    async def get_mcp_credential(
        self, user_id: str, server_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve MCP server credentials from PostgreSQL.

        Args:
            user_id: User ID
            server_id: MCP server ID

        Returns:
            Dictionary with credential data or None if not found
        """
        async with get_db_session() as session:
            stmt = select(MCPCredential).where(
                MCPCredential.user_id == user_id,
                MCPCredential.server_id == server_id,
            )
            result = await session.execute(stmt)
            credential = result.scalar_one_or_none()

            if not credential:
                return None

            return {
                "auth_type": credential.auth_type,
                "bearer_token": credential.bearer_token,
                "oauth_access_token": credential.oauth_access_token,
                "oauth_refresh_token": credential.oauth_refresh_token,
                "oauth_client_id": credential.oauth_client_id,
                "oauth_client_secret": credential.oauth_client_secret,
                "basic_username": credential.basic_username,
                "basic_password": credential.basic_password,
                "custom_headers": json.loads(credential.custom_headers)
                if credential.custom_headers
                else None,
                "expires_at": credential.expires_at,
                "scopes": credential.scopes,
            }

    async def delete_mcp_credential(self, user_id: str, server_id: int) -> bool:
        """
        Delete MCP server credentials.

        Args:
            user_id: User ID
            server_id: MCP server ID

        Returns:
            True if successful
        """
        async with get_db_session() as session:
            stmt = select(MCPCredential).where(
                MCPCredential.user_id == user_id,
                MCPCredential.server_id == server_id,
            )
            result = await session.execute(stmt)
            credential = result.scalar_one_or_none()

            if not credential:
                return False

            await session.delete(credential)
            await session.commit()
            logger.info(
                f"Deleted MCP credentials for user {user_id}, server {server_id}"
            )
            return True

    async def refresh_mcp_oauth_token(
        self, user_id: str, server_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Refresh OAuth token for MCP server.

        Args:
            user_id: User ID
            server_id: MCP server ID

        Returns:
            Updated credential data or None if refresh failed
        """
        credential = await self.get_mcp_credential(user_id, server_id)
        if not credential or credential["auth_type"] != MCPAuthType.OAUTH2.value:
            logger.warning(
                f"Cannot refresh MCP token: Invalid credential for server {server_id}"
            )
            return None

        refresh_token = credential.get("oauth_refresh_token")
        if not refresh_token:
            logger.warning(
                f"Cannot refresh MCP token: No refresh token for server {server_id}"
            )
            return None

        # TODO: Implement OAuth refresh logic based on server's OAuth provider
        # For now, this is a placeholder that would need to be implemented
        # based on the specific OAuth provider being used
        logger.warning(
            f"MCP OAuth token refresh not yet implemented for server {server_id}"
        )
        return None


# Singleton instance
token_repository = TokenRepository()
