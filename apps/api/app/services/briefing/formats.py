"""How the brief writes the things it says more than once: days, times and a text's opening line.

Every date a brief's models read is a day: "Sat Nov 14". The user-facing quiet note keeps
its weekday whole ("on Saturday Nov 14").
"""

from datetime import date, datetime, time


def day(on: date) -> str:
    """Say a day the one way a brief's models read it: "Sat Nov 14"."""
    return on.strftime("%a %b %-d")


def dated(on: date) -> str:
    """Say a day with its year: "Sat Nov 14, 2026"."""
    return f"{day(on)}, {on.year}"


def long_day(on: date) -> str:
    """Say a day with its weekday whole, as the quiet note does: "Saturday Nov 14"."""
    return on.strftime("%A %b %-d")


def weekday(on: date) -> str:
    """Say a day's weekday: "Saturday"."""
    return on.strftime("%A")


def short_weekday(on: date) -> str:
    """Say a day's weekday short: "Sat"."""
    return on.strftime("%a")


def clock_time(at: datetime | time) -> str:
    """Say a time on the user's clock: "4:00 PM"."""
    return at.strftime("%-I:%M %p")


def moment(at: datetime) -> str:
    """Say a moment on the user's clock: "Sat Nov 14, 8:00 AM"."""
    return f"{day(at.date())}, {clock_time(at)}"


def opening_line(text: str) -> str:
    """Return a text's first non-blank line, stripped; empty when it has none."""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")
