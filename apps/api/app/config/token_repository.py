"""
Integration Token Repository.

This module provides centralized management for integration OAuth tokens (Google, Slack, Notion, etc.)
using PostgreSQL via SQLAlchemy. It handles token storage, retrieval, refreshing, and updates for
third-party service integrations.

Note: User authentication via WorkOS is handled separately by the WorkOSAuthMiddleware.
"""

from datetime import UTC, datetime, timedelta
import json
from typing import TypedDict, cast

from authlib.integrations.starlette_client import OAuth
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from authlib.oauth2.rfc6749 import OAuth2Token
from fastapi import HTTPException
import httpx
from sqlalchemy import select, update

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.providers import CredentialProviderName
from app.db.postgresql import get_db_session
from app.models.db_oauth import OAuthToken
from app.services.providers.provider_credentials_service import (
    GoogleOAuthClient,
    google_oauth_client,
    resolve as resolve_provider_config,
)
from shared.py.wide_events import log


async def resolve_google_oauth_credentials() -> GoogleOAuthClient | None:
    """Return the Google OAuth client id and secret, store credential first.

    The stored google_oauth credential carries the client secret as its api_key
    field; the client id has no stored representation and comes from the
    environment. Returns None unless both halves resolve: a half-configured
    Google must never reach an OAuth endpoint.
    """
    return google_oauth_client(await resolve_provider_config(CredentialProviderName.GOOGLE_OAUTH))


class GoogleTokenData(TypedDict, total=False):
    """The OAuth token fields this module reads off a Google token response.

    A partial shape on purpose: Google's endpoint returns more than we consume
    and the row is stored verbatim elsewhere, so the fields read here are the
    declared contract rather than the whole payload.
    """

    expires_at: str | int | float | None
    expires_in: str | int | float | None
    access_token: str | None
    refresh_token: str | None
    token_type: str | None
    scope: str | None


class TokenRepository:
    """
    Repository for managing integration OAuth tokens in PostgreSQL.

    This class handles tokens for third-party integrations like Google, Slack, Notion, etc.
    It does NOT handle WorkOS authentication tokens, which are managed by WorkOSAuthMiddleware.
    """

    def __init__(self) -> None:
        """Initialize the token repository."""

        self.oauth = OAuth()
        # The Google client registers lazily on first use: credentials can
        # come from the credential store (Mongo), which is unreachable at
        # import time where this singleton is constructed.
        self._google_client: StarletteOAuth2App | None = None

        log.info(
            f"{LogTag.STARTUP} Token repository initialized for managing API tokens (Google, etc.)"
        )

    async def _ensure_google_client(self) -> StarletteOAuth2App | None:
        """Return the Google OAuth client, registered on first need; None if unconfigurable.

        Resolution runs store → env on every call until it succeeds, so a
        credential saved in Settings takes effect without a restart. Once
        registered the client is reused as-is (re-registering mid-flight
        could swap credentials under an active flow).
        """
        if self._google_client is not None:
            return self._google_client

        credentials = await resolve_google_oauth_credentials()
        if credentials is None:
            log.warning(
                f"{LogTag.STARTUP} Google OAuth credentials not found "
                "(no stored credential, no GOOGLE_CLIENT_ID/SECRET env), client not registered"
            )
            return None

        client_id, client_secret = credentials
        self._google_client = self.oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid email profile",
                "prompt": "select_account",
            },
        )
        log.info(f"{LogTag.STARTUP} Google OAuth client registered")
        return self._google_client

    def _get_token_expiration(self, token_data: GoogleTokenData) -> datetime:
        """Get token expiration time with fallback logic."""

        # Try expires_at first (epoch seconds are UTC).
        expires_at = token_data.get("expires_at")
        if expires_at is not None:
            try:
                return datetime.fromtimestamp(float(expires_at), UTC)
            except (ValueError, TypeError, OverflowError):
                log.warning(f"{LogTag.STARTUP} Invalid expires_at", expires_at=expires_at)

        # Fall back to expires_in
        expires_in = token_data.get("expires_in", 3500)  # Default about 1 hour
        try:
            expires_in = float(expires_in)
            return datetime.now(UTC) + timedelta(seconds=expires_in)
        except (ValueError, TypeError):
            log.warning(
                f"{LogTag.STARTUP} Invalid expires_in, using default", expires_in=expires_in
            )
            return datetime.now(UTC) + timedelta(seconds=3600)

    async def store_token(
        self, user_id: str, provider: str, token_data: GoogleTokenData
    ) -> OAuth2Token:
        """Store a new integration OAuth token in the database."""
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
            if not refresh_token_value and existing_token and existing_token.refresh_token:
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
                        updated_at=datetime.now(UTC),
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
        """Retrieve an integration token for a user and provider."""
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

            # Parse token data from JSON for additional fields. Bound to the
            # declared shape rather than read off a bare json.loads dict.
            token_data: GoogleTokenData = json.loads(token_record.token_data)

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

    async def _refresh_google_token(self, refresh_token: str) -> OAuth2Token | None:
        """Refresh a Google OAuth token using the refresh token."""

        client = await self._ensure_google_client()
        if client is None:
            log.error(f"{LogTag.STARTUP} Google OAuth client not properly initialized")
            return None

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
                log.error(f"{LogTag.STARTUP} Failed to refresh token", text=response.text)
                return None

            token_data = response.json()

            # Google refresh token responses don't include the refresh token
            # Add it back to maintain the full token
            token_data["refresh_token"] = refresh_token

            # Create OAuth2Token from response
            return OAuth2Token(token_data)
        except Exception as e:
            log.error(
                f"{LogTag.STARTUP} Error refreshing Google token",
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def _refresh_provider_token(
        self, provider: str, refresh_token: str
    ) -> OAuth2Token | None:
        """Dispatch token refresh to the appropriate provider-specific method."""
        if provider == "google":
            return await self._refresh_google_token(refresh_token)
        # Add more providers as needed
        log.error(f"{LogTag.STARTUP} Provider not supported for token refresh", provider=provider)
        return None

    async def refresh_token(self, user_id: str, provider: str) -> OAuth2Token | None:
        """Refresh an expired integration token."""
        # Get the token record for this provider
        async with get_db_session() as session:
            stmt = select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == provider
            )
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                log.warning(
                    f"{LogTag.STARTUP} Cannot refresh token: No token found for user",
                    provider=provider,
                    user_id=user_id,
                )
                return None

            # Check if refresh token is available
            refresh_token = token_record.refresh_token
            if not refresh_token:
                log.warning(
                    f"{LogTag.STARTUP} Cannot refresh token: No refresh token for user and provider",
                    user_id=user_id,
                    provider=provider,
                )
                return None

            # Refresh the token using the appropriate provider handler
            try:
                log.info(
                    f"{LogTag.STARTUP} Refreshing token for user",
                    provider=provider,
                    user_id=user_id,
                )
                token = await self._refresh_provider_token(provider, refresh_token)

                if not token:
                    log.error(
                        f"{LogTag.STARTUP} Failed to refresh token for user",
                        provider=provider,
                        user_id=user_id,
                    )
                    return None

                # Convert OAuth2Token to a dictionary we can store. `token` is
                # the oauthlib token; bind the declared shape so the reads below
                # are key-checked rather than left to inference.
                token_params: GoogleTokenData = cast(GoogleTokenData, token)
                token_dict: GoogleTokenData = {
                    "access_token": token_params.get("access_token"),
                    "token_type": token_params.get("token_type", "Bearer"),
                    "scope": token_params.get("scope", token_record.scopes),
                    "expires_in": token_params.get("expires_in"),
                    "expires_at": token_params.get("expires_at"),
                }

                # Preserve the refresh token
                # If the new token has a refresh token, use it; otherwise keep the existing one
                token_dict["refresh_token"] = token_params.get(
                    "refresh_token", token_record.refresh_token
                )

                # Store the refreshed token using our existing store_token method
                # This will return the properly formatted OAuth2Token object directly
                # without querying the database again
                refreshed_token = await self.store_token(user_id, provider, token_dict)

                log.info(
                    f"{LogTag.STARTUP} Successfully refreshed token for user",
                    provider=provider,
                    user_id=user_id,
                )

                return refreshed_token
            except Exception as e:
                log.error(
                    f"{LogTag.STARTUP} Error refreshing token",
                    provider=provider,
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )
                return None

    async def revoke_token(self, user_id: str, provider: str) -> bool:
        """Revoke an integration token."""

        async with get_db_session() as session:
            # Find the token for the specific provider
            stmt = select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == provider
            )
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                log.warning(
                    f"{LogTag.STARTUP} Cannot revoke token: No token found for user",
                    provider=provider,
                    user_id=user_id,
                )
                return False

            try:
                await session.delete(token_record)
                await session.commit()
                log.info(
                    f"{LogTag.STARTUP} Successfully revoked token for user",
                    provider=provider,
                    user_id=user_id,
                )
                return True
            except Exception as e:
                log.error(
                    f"{LogTag.STARTUP} Error revoking token",
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )
                await session.rollback()
                return False


# Singleton instance
token_repository = TokenRepository()
