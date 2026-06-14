"""Canonical timezone module — the single source of truth for the API.

Timezones bite because a bare ``str`` can secretly be an IANA name
(``"Asia/Kolkata"``), a fixed offset (``"+05:30"``), ``"UTC"``, ``""`` or
``None``, and nothing forces a caller to say which. This module makes illegal
states unrepresentable: the :class:`Timezone` value object is *always valid*
(constructed only via :meth:`Timezone.parse` / :meth:`Timezone.try_parse`), so
``.tzinfo`` always resolves and no consumer ever re-implements parsing. Bare
``str`` survives only at the Mongo / HTTP / LangGraph-config boundaries.

Two distinct concepts (do not cross them):

* **Home timezone** — where the user lives. Drives the agent's "now",
  notification/display formatting, todos, and the *default* for a new schedule.
  Resolved by :func:`resolve_home_timezone` (DB profile, healed from header).
* **Schedule timezone** — the wall-clock zone one specific cron/reminder/event
  fires in. Stored on the task; passed explicitly to cron math. Defaults to the
  home timezone at creation time, but is independent thereafter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone as _timezone, tzinfo as _tzinfo
from enum import Enum
import re
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig

from shared.py.wide_events import log

# ``±HH:MM`` fixed-offset form (e.g. "+05:30", "-08:00").
_OFFSET_RE = re.compile(r"^[+-]\d{2}:\d{2}$")


def _offset_value(total_seconds: int) -> str:
    """Render a whole-second UTC offset as a canonical ``±HH:MM`` string."""
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    return f"{sign}{total_seconds // 3600:02d}:{total_seconds % 3600 // 60:02d}"


def _canonical_from_tzinfo(tz: _tzinfo) -> str:
    """Best canonical string for an arbitrary ``tzinfo`` (IANA key or offset)."""
    key = getattr(tz, "key", None)  # ZoneInfo exposes its IANA name here
    if key:
        return str(key)
    if tz is UTC:
        return "UTC"
    offset = tz.utcoffset(None)
    return _offset_value(int(offset.total_seconds())) if offset is not None else "UTC"


class Timezone:
    """An always-valid timezone: an IANA name, a fixed UTC offset, or UTC.

    There is no public way to hold an invalid ``Timezone`` — construct via
    :meth:`parse` / :meth:`try_parse`, so every consumer can rely on
    :attr:`tzinfo` resolving and never re-parse a raw string itself.
    """

    __slots__ = ("tzinfo", "value")

    value: str
    tzinfo: _tzinfo

    def __init__(self, value: str, tzinfo: _tzinfo) -> None:
        # Construct through parse()/try_parse()/utc(); these guarantee validity.
        self.value = value
        self.tzinfo = tzinfo

    @classmethod
    def utc(cls) -> Timezone:
        """The UTC timezone."""
        return cls("UTC", UTC)

    @classmethod
    def parse(cls, raw: str | _tzinfo | Timezone | None) -> Timezone:
        """Parse any reasonable input into a ``Timezone``.

        Accepts an existing ``Timezone`` (idempotent), a ``tzinfo``, an IANA
        name, a ``±HH:MM`` offset, ``"UTC"``, or ``None``. Falls back to UTC
        (with a warning) for blank/unrecognized input, so format and
        notification paths never raise on a bad stored preference.
        """
        parsed = cls.try_parse(raw)
        if parsed is not None:
            return parsed
        if raw is not None and not isinstance(raw, (Timezone, _tzinfo)):
            log.warning("Timezone.parse: unrecognized timezone, using UTC", timezone=raw)
        return cls.utc()

    @classmethod
    def try_parse(cls, raw: str | _tzinfo | Timezone | None) -> Timezone | None:
        """Like :meth:`parse` but returns ``None`` for blank/invalid input.

        Distinguishes "no usable zone" from an explicit ``"UTC"`` (which yields
        ``Timezone.utc()``) — required by :func:`resolve_home_timezone`.
        """
        if isinstance(raw, Timezone):
            return raw
        if raw is None:
            return None
        if isinstance(raw, _tzinfo):
            return cls(_canonical_from_tzinfo(raw), raw)
        candidate = raw.strip()
        if not candidate:
            return None
        if candidate.upper() == "UTC":
            return cls.utc()
        if _OFFSET_RE.match(candidate):
            sign = 1 if candidate[0] == "+" else -1
            delta = timedelta(hours=int(candidate[1:3]), minutes=int(candidate[4:6]))
            return cls(candidate, _timezone(sign * delta))
        try:
            return cls(candidate, ZoneInfo(candidate))
        except Exception:
            return None

    @classmethod
    def of_offset(cls, instant: datetime | None) -> Timezone | None:
        """The fixed-offset ``Timezone`` matching a tz-aware datetime's offset.

        Returns ``None`` for a naive/``None`` datetime (caller then falls back to
        UTC). Used to capture a user's offset for later recurrence math when only
        an offset — not an IANA name — is available.
        """
        if instant is None or instant.tzinfo is None:
            return None
        offset = instant.utcoffset()
        if offset is None:
            return None
        return cls.try_parse(_offset_value(int(offset.total_seconds())))

    @property
    def is_utc(self) -> bool:
        """Whether this is UTC."""
        return self.value.upper() == "UTC"

    @property
    def is_offset_only(self) -> bool:
        """True for a fixed ``±HH:MM`` offset (DST-naive); False for IANA/UTC."""
        return bool(_OFFSET_RE.match(self.value))

    def now(self) -> datetime:
        """Current instant expressed in this zone (tz-aware)."""
        return datetime.now(self.tzinfo)

    def localize(self, instant: datetime) -> datetime:
        """``instant`` (any tz-aware datetime) re-expressed in this zone."""
        return instant.astimezone(self.tzinfo)

    def format(self, instant: datetime, fmt: str = "%I:%M %p %Z") -> str:
        """Render ``instant`` as local time, leading zero stripped (``"9:05 AM"``)."""
        return self.localize(instant).strftime(fmt).lstrip("0")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Timezone) and other.value == self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return f"Timezone({self.value!r})"

    def __str__(self) -> str:
        return self.value


def is_valid_timezone(raw: str | None) -> bool:
    """Whether ``raw`` is a usable IANA name or ``±HH:MM`` offset (``"UTC"`` ok)."""
    return Timezone.try_parse(raw) is not None


class TimezoneSource(str, Enum):
    """Which input produced a resolved home timezone (emitted for observability)."""

    USER_PROFILE = "user_profile"
    X_TIMEZONE_HEADER = "x_timezone_header"
    AGENT_CONFIG = "agent_config"
    FALLBACK_UTC = "fallback_utc"


@dataclass(frozen=True, slots=True)
class ResolvedTimezone:
    """Result of resolving a user's home timezone."""

    timezone: Timezone
    source: TimezoneSource
    should_heal: bool  # write the resolved zone back to user.timezone (DB)


def resolve_home_timezone(stored: str | None, header: str | None) -> ResolvedTimezone:
    """The one home-timezone precedence rule, pure and side-effect-free.

    1. A real (non-UTC) stored ``user.timezone`` is authoritative.
    2. Else (empty OR low-confidence ``"UTC"`` — often a junk default that then
       sticks forever and silently runs everything in UTC) a valid non-UTC
       header wins, and ``should_heal`` asks the caller to backfill the DB so
       header-less background paths converge.
    3. Else a genuine stored ``"UTC"``, else UTC.
    """
    stored_tz = Timezone.try_parse(stored)
    if stored_tz is not None and not stored_tz.is_utc:
        return ResolvedTimezone(stored_tz, TimezoneSource.USER_PROFILE, should_heal=False)

    header_tz = Timezone.try_parse(header)
    if header_tz is not None and not header_tz.is_utc:
        return ResolvedTimezone(header_tz, TimezoneSource.X_TIMEZONE_HEADER, should_heal=True)

    return ResolvedTimezone(
        stored_tz or Timezone.utc(), TimezoneSource.FALLBACK_UTC, should_heal=False
    )


def home_timezone_from_config(config: RunnableConfig) -> Timezone:
    """Home timezone from a LangGraph ``configurable`` (agent runs).

    The agent config carries a ``±HH:MM`` ``user_timezone`` set at run assembly.
    Falls back to UTC with a loud warning — the silent-UTC drift that fires
    scheduled work at the wrong hour.
    """
    raw = (config.get("configurable") or {}).get("user_timezone")
    if raw:
        log.set(timezone_source=TimezoneSource.AGENT_CONFIG.value, user_timezone=raw)
        return Timezone.parse(raw)
    log.set(timezone_source=TimezoneSource.FALLBACK_UTC.value, user_timezone="+00:00")
    log.warning("home_timezone_from_config: no user_timezone in config; using UTC")
    return Timezone.utc()


def format_local_time(
    instant: datetime, timezone_name: str | None, fmt: str = "%I:%M %p %Z"
) -> str:
    """Render ``instant`` (tz-aware) as local time in ``timezone_name``.

    Convenience wrapper over ``Timezone.parse(...).format(...)`` for the many
    string-in callers (notifications); offset-aware and never raises.
    """
    return Timezone.parse(timezone_name).format(instant, fmt)


def is_within_local_daytime(
    instant: datetime, timezone_name: str | None, start_hour: int, end_hour: int
) -> bool:
    """Whether ``instant`` falls inside ``[start_hour, end_hour)`` local time."""
    local_hour = Timezone.parse(timezone_name).localize(instant).hour
    return start_hour <= local_hour < end_hour


# Commonly used timezone constants for convenience.
TIMEZONE_UTC = UTC
TIMEZONE_KOLKATA = "Asia/Kolkata"
TIMEZONE_NEW_YORK = "America/New_York"
TIMEZONE_LONDON = "Europe/London"
TIMEZONE_TOKYO = "Asia/Tokyo"
