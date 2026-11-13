"""Reminder scheduling constants."""

from datetime import timedelta

# A reminder created without an explicit stop_after stops recurring this long after creation.
REMINDER_DEFAULT_LIFETIME = timedelta(days=180)

# What the agent is told when the reminder it asked for was already set, so it
# tells the user that instead of claiming a second one.
REMINDER_ALREADY_EXISTS_RESULT = (
    "This reminder was already set with the same text and time; no second one was created."
)

# Serializes creating one reminder (same user, text and schedule) across replicas,
# so two identical asks at once still find each other. The critical section is
# one find plus one insert, so a short lease is plenty.
REMINDER_CREATE_LOCK_PREFIX = "reminder_create:"
REMINDER_CREATE_LOCK_LEASE_SECONDS = 10
REMINDER_CREATE_LOCK_RENEW_SECONDS = 5
REMINDER_CREATE_LOCK_ACQUIRE_TIMEOUT_SECONDS = 10
REMINDER_CREATE_LOCK_MAX_HOLD_SECONDS = 30
