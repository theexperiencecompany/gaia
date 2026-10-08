"""Auth events: signup, login, logout and session resume."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class UserSignedUp(ServerEvent):
    """A new user account was created."""

    event: ClassVar[str] = "user:signed_up"

    # WorkOS's authentication_method (GoogleOAuth, MagicAuth, ...); absent when WorkOS reports none.
    signup_method: Identifier | None = None
    # True on an event a backfill sent at its record's own time; new-signup tiles exclude it.
    backfilled: bool | None = None


class UserLoggedIn(ServerEvent):
    """An existing user logged in."""

    event: ClassVar[str] = "user:logged_in"

    # WorkOS's authentication_method (GoogleOAuth, MagicAuth, ...); absent when WorkOS reports none.
    login_method: Identifier | None = None


class UserLoggedOut(ServerEvent):
    """A user logged out."""

    event: ClassVar[str] = "user:logged_out"


class UserSessionResumed(WebEvent):
    """A browser resumed a signed-in session from its cookie, once per tab session."""

    event: ClassVar[str] = "user:session_resumed"

    method: Literal["wos_session_cookie"]
    has_completed_onboarding: bool
