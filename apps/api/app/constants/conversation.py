"""Conversation runtime constants."""

from datetime import timedelta

# p90 time to a first reply is about 16s, so a newer input inside this window still beats waiting.
RESTART_WINDOW_SECONDS = 20.0
RESTART_WINDOW = timedelta(seconds=RESTART_WINDOW_SECONDS)
