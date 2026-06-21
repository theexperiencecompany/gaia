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
