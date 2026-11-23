"""What a run that interrupts the user's quiet hours is told, and how its report opens."""

# Opens the message of a run that interrupts the user's quiet hours.
QUIET_HOURS_BYPASS_OPENING = "I'm interrupting your quiet hours because {reason}."
# Carried by a run its gate let through quiet hours; it beats a rule to stay quiet at night.
QUIET_HOURS_BYPASS_NOTE = (
    "quiet-hours bypass: {reason}. It is inside the user's quiet hours and this event is why "
    "this run interrupts them: report as you would outside quiet hours, and open your report "
    "with this line: " + QUIET_HOURS_BYPASS_OPENING
)
