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

# Sandbox server-side lifetime (seconds), refreshed via `set_timeout()` on reuse
# so an active sandbox is never killed mid-session. 3600 is the E2B Hobby-tier
# ceiling (Pro allows up to 86_400) — raise if the account is on Pro.
SANDBOX_LIFETIME_SECONDS = 3600

# Bound on a single connect control-plane call (seconds) so a hung E2B control
# plane falls through to a fresh create instead of stalling the agent.
SANDBOX_CONNECT_TIMEOUT_SECONDS = 10

# Only refresh a reused sandbox's kill timer once this many seconds have elapsed
# since the last refresh — avoids a set_timeout round-trip on every tool call in
# a rapid turn. Half the lifetime leaves ample slack before the deadline.
SANDBOX_TIMEOUT_REFRESH_SECONDS = SANDBOX_LIFETIME_SECONDS // 2

# Serializes sandbox acquisition per user across replicas, or two pods
# create/resume the same sandbox at once. Short lease renewed by a watchdog,
# since cold create + JuiceFS mount has no useful upper bound to size it to.
SANDBOX_LOCK_LEASE_SECONDS = 30
SANDBOX_LOCK_RENEW_SECONDS = 10
# A waiter blocks this long before giving up; longer than the mount script's
# 120s so a queue behind a genuinely slow create waits rather than failing.
SANDBOX_LOCK_ACQUIRE_TIMEOUT_SECONDS = 180
# Hard cap on watchdog renewal; past this the lease expires so a hung-but-alive
# holder can't block the user forever. Comfortably above the real critical
# section (cold create + 120s mount).
SANDBOX_LOCK_MAX_HOLD_SECONDS = 300
