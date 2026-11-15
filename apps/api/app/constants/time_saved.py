"""How much time GAIA's recorded work is estimated to save, per kind of work.

These are deliberately conservative estimates, not measurements: GAIA records
how many things it did, never how long a person would have taken to do them.
"""

from datetime import timedelta

# One metered action on the activity heatmap (a chat reply, a search, a draft,
# a calendar or todo change): about what a person spends doing it by hand.
MINUTES_SAVED_PER_ACTION = 2

# One workflow run that succeeded: a multi-step routine (triage, a digest, a
# follow-up round) a person would otherwise sit down and do.
MINUTES_SAVED_PER_WORKFLOW_RUN = 10

# The recap covers the seven UTC days before the day it is shown on.
TIME_SAVED_WINDOW = timedelta(days=7)
