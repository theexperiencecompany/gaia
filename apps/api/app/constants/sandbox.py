"""
E2B sandbox constants.

Centralized tunables for the per-user coding sandbox: command timeouts,
input bounds, and health-probe windows. Import these instead of redefining
local literals in the sandbox lifecycle and coding tools.
"""

# Bash tool command execution (seconds), forwarded to E2B as the server-side
# command-stream deadline. Generous because coding is paid-tier, with long jobs
# (builds, large installs) expected.
BASH_DEFAULT_TIMEOUT_SECONDS = 300
BASH_MAX_TIMEOUT_SECONDS = 1800

# Maximum length of a single shell command string accepted by the bash tool.
BASH_MAX_COMMAND_LENGTH = 16_000

# Suffix for the in-flight temp file used by atomic writes (write/edit write here
# then rename into place). The artifact watcher filters events for this suffix so
# a half-written temp file never surfaces as an artifact — keep them in sync.
WORKSPACE_TMP_SUFFIX = ".gaia-tmp"

# Health-probe windows (seconds). `is_running()` hits E2B's GET /health; we
# bound both the request itself and the surrounding wait so a hung control
# plane never stalls sandbox acquisition.
HEALTH_PROBE_REQUEST_TIMEOUT_SECONDS = 4
HEALTH_PROBE_WAIT_TIMEOUT_SECONDS = 5
# Second probe once E2B says the sandbox is running: a live sandbox misses the
# first one about 1 in 60 times (p95 2.7s, max 4.8s measured), a wedged one never answers.
HEALTH_PROBE_RETRY_REQUEST_TIMEOUT_SECONDS = 14
HEALTH_PROBE_RETRY_WAIT_TIMEOUT_SECONDS = 15

# Home of the sandbox's unprivileged user (E2B's default "user"; see
# mount_juicefs.sh SANDBOX_USER). Local root disk, unlike /workspace (JuiceFS).
SANDBOX_USER_HOME = "/home/user"

# E2B kill-timer lifetime (seconds) of a regular sandbox, refreshed on reuse; a lost
# in-process idle pause costs at most this. Lab: settings.E2B_AGENT_LAB_LIFETIME_SECONDS.
SANDBOX_LIFETIME_SECONDS = 3600

# Bound on a single connect control-plane call (seconds) so a hung E2B control
# plane falls through to a fresh create instead of stalling the agent.
SANDBOX_CONNECT_TIMEOUT_SECONDS = 10


# The slow cold-create steps inside the user's lock: the JuiceFS mount script
# (its readiness poll is ~105s worst case) and an agent-lab home restore.
SANDBOX_MOUNT_TIMEOUT_SECONDS = 120
SANDBOX_AGENTS_SETUP_TIMEOUT_SECONDS = 300

# Serializes sandbox acquisition per user across replicas: a short lease a
# watchdog renews, since a cold create has no useful upper bound to size it to.
SANDBOX_LOCK_LEASE_SECONDS = 30
SANDBOX_LOCK_RENEW_SECONDS = 10
# Hard cap on watchdog renewal: the slowest cold create (E2B create, mount,
# restore) plus margin, so a hung-but-alive holder still cannot block forever.
SANDBOX_LOCK_MAX_HOLD_SECONDS = (
    SANDBOX_MOUNT_TIMEOUT_SECONDS + SANDBOX_AGENTS_SETUP_TIMEOUT_SECONDS + 120
)
# A waiter outlasts a full hold, so a queue behind a slow create waits rather than failing.
SANDBOX_LOCK_ACQUIRE_TIMEOUT_SECONDS = SANDBOX_LOCK_MAX_HOLD_SECONDS + 60
