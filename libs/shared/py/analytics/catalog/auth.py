"""Auth and activity events: signup, login, logout, session resume and the daily active mark."""

from datetime import timedelta
from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class UserSignedUp(ServerEvent):
    """A new user account was created."""

    event: ClassVar[str] = "user:signed_up"
    budget_per_user_day: ClassVar[int] = 10

    # WorkOS's authentication_method (GoogleOAuth, MagicAuth, ...); absent when WorkOS reports none.
    signup_method: Identifier | None = None


class UserLoggedIn(ServerEvent):
    """An existing user logged in."""

    event: ClassVar[str] = "user:logged_in"
    budget_per_user_day: ClassVar[int] = 100

    # WorkOS's authentication_method (GoogleOAuth, MagicAuth, ...); absent when WorkOS reports none.
    login_method: Identifier | None = None


class UserLoggedOut(ServerEvent):
    """A user logged out."""

    event: ClassVar[str] = "user:logged_out"
    budget_per_user_day: ClassVar[int] = 10


class UserActive(ServerEvent):
    """A user did something themselves today, on any surface: the one definition of an active user.

    Emitted by the server capture function on a user's first actor=user event of
    the IST day, never by a call site.
    """

    event: ClassVar[str] = "user:active"
    budget_per_user_day: ClassVar[int] = 1
    # Outlives the IST day it keys, so a late retry still finds the gate.
    at_most_once_ttl: ClassVar[timedelta | None] = timedelta(hours=48)


class UserSessionResumed(WebEvent):
    """A browser resumed a signed-in session from its cookie, once per tab session."""

    event: ClassVar[str] = "user:session_resumed"
    budget_per_user_day: ClassVar[int] = 20

    method: Literal["wos_session_cookie"]
    has_completed_onboarding: bool
