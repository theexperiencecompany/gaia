"""Activation checklist ("first steps") constants."""

# The ``users`` subdocument holding the checklist's only persisted state — whether
# the user collapsed it. Every step's ``done`` is derived from a real signal at
# read time.
FIRST_STEPS_FIELD = "first_steps"
FIRST_STEPS_COLLAPSED_FIELD = f"{FIRST_STEPS_FIELD}.collapsed"
FIRST_STEPS_COLLAPSED_AT_FIELD = f"{FIRST_STEPS_FIELD}.collapsed_at"
