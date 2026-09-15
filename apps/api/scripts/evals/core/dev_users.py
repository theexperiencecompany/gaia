"""Minting and impersonating the throwaway users the live-chat harnesses run as.

Four scripts each carried their own ``_provision``, and all four did the same
three things in the same order: mint a dev user, grant it Pro (the API is
paid-only, so a turn from a free user is a 402 before it ever reaches the agent),
then write an onboarding profile through the real PATCH so the product's own
prewarm fills the cache the agent reads back.

The order matters and is the reason this is one function rather than three:
granting Pro before the user exists is a no-op, and PATCHing preferences before
the grant races the paywall. Getting that wrong shows up as a report full of
402s, which reads like a model regression.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import httpx

from app.models.user_models import OnboardingPreferences

#: Where ``grant_pro_access.py`` lives, relative to ``apps/api`` (the cwd every
#: eval script is run from).
GRANT_SCRIPT = "scripts/grant_pro_access.py"

#: The display name a minted dev user gets when a script does not care.
DEFAULT_NAME = "Alex"


def dev_client(email: str) -> httpx.AsyncClient:
    """A client that is authenticated as ``email`` on the dev bypass.

    Both the header and the cookie are sent because the bypass is read from
    either depending on the route: REST endpoints take ``X-Dev-User``, and the
    chat stream reads the cookie. Sending one and not the other authenticates
    for part of a run and 401s for the rest.
    """
    return httpx.AsyncClient(
        headers={"X-Dev-User": email},
        cookies={"dev_bypass_user": email},
    )


async def mint(
    client: httpx.AsyncClient, api_url: str, email: str, name: str = DEFAULT_NAME
) -> None:
    """Create the dev user. Idempotent on the API side, so a re-run is safe."""
    await client.post(f"{api_url}/api/v1/dev/users", json={"email": email, "name": name})


async def grant_pro(email: str) -> None:
    """Give the dev user a subscription.

    Run through the real script rather than by writing Mongo directly: the eval
    is meant to exercise the paid path the product uses, and a hand-written
    subscription document is exactly the kind of drift that makes a green eval
    lie about a broken paywall.
    """
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, GRANT_SCRIPT, "--email", email],
        check=True,
        capture_output=True,
    )


async def set_preferences(
    client: httpx.AsyncClient, api_url: str, email: str, preferences: OnboardingPreferences
) -> None:
    """Write onboarding answers through the product's own PATCH."""
    await client.patch(
        f"{api_url}/api/v1/onboarding/preferences",
        headers={"X-Dev-User": email},
        json=preferences.model_dump(mode="json", exclude_none=True),
    )


async def provision(
    api_url: str,
    email: str,
    preferences: OnboardingPreferences | None = None,
    *,
    name: str = DEFAULT_NAME,
) -> None:
    """A fresh Pro dev user, optionally carrying an onboarding profile.

    ``preferences`` is optional only so a caller that genuinely wants the
    default-onboarding state can say so explicitly; every current caller passes
    one, because what the agent says to a new user is mostly a function of it.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        await mint(client, api_url, email, name)
        await grant_pro(email)
        if preferences is not None:
            await set_preferences(client, api_url, email, preferences)
