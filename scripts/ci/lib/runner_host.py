"""Say whether this job runs on the home box, as lib/runner-host.sh does for bash."""

from __future__ import annotations

import os

# The box's runners are gaia-home-<n> (gaia-infra setup.sh RUNNER_NAME_PREFIX); the
# runner kind cannot tell it from Blacksmith, which reports self-hosted too.
BOX_RUNNER_NAME_PREFIX = "gaia-home-"


def on_the_box() -> bool:
    return os.environ.get("RUNNER_NAME", "").startswith(BOX_RUNNER_NAME_PREFIX)
