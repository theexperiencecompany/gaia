"""
E2B sandbox constants.

Centralized tunables for the per-user coding sandbox: command timeouts,
input bounds, and health-probe windows. Import these instead of redefining
local literals in the sandbox lifecycle and coding tools.
"""

# Bash tool command execution (seconds). `timeout` is forwarded to E2B as the
# server-side command-stream deadline. The cap is generous because coding is a
# paid-tier feature where long-running jobs (builds, large installs, data work)
# are expected.
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

# Sandbox server-side lifetime (seconds). Passed to `create()` and refreshed via
# `set_timeout()` on reuse so an actively-used sandbox is never killed mid-session.
# E2B kills a sandbox once this window elapses; 3600 is the Hobby-tier ceiling
# (Pro allows up to 86_400) — raise if the account is on a Pro plan.
SANDBOX_LIFETIME_SECONDS = 3600

# Bound on a single connect control-plane call (seconds) so a hung E2B control
# plane falls through to a fresh create instead of stalling the agent.
SANDBOX_CONNECT_TIMEOUT_SECONDS = 10

# Only refresh a reused sandbox's kill timer once this many seconds have elapsed
# since the last refresh — avoids a set_timeout round-trip on every tool call in
# a rapid turn. Half the lifetime leaves ample slack before the deadline.
SANDBOX_TIMEOUT_REFRESH_SECONDS = SANDBOX_LIFETIME_SECONDS // 2

# --- Cross-replica acquisition lock ---
# Sandbox acquisition must be serialized per user across every replica, or two
# pods create/resume the same user's sandbox at once (double E2B billing, an
# orphaned sandbox, a lost pool entry).
#
# The lease is deliberately short and renewed by a watchdog rather than set long
# enough to cover the work. The critical section has no useful upper bound — it
# can include a cold create plus the JuiceFS mount script — so any fixed TTL is
# either too short (it expires mid-flight and a second pod enters) or so long
# that a crashed holder blocks the user for minutes. Renewing decouples
# correctness from how long the work takes.
SANDBOX_LOCK_LEASE_SECONDS = 30
SANDBOX_LOCK_RENEW_SECONDS = 10
# A waiter blocks this long before giving up; longer than the mount script's
# 120s so a queue behind a genuinely slow create waits rather than failing.
SANDBOX_LOCK_ACQUIRE_TIMEOUT_SECONDS = 180
# Hard cap on how long the watchdog will keep renewing. Past this the lease is
# allowed to expire so a hung-but-alive holder (stuck create/mount) can't block
# the user forever; comfortably above the real critical section (cold create +
# 120s mount) so a legitimate slow acquire is never evicted mid-flight.
SANDBOX_LOCK_MAX_HOLD_SECONDS = 300
