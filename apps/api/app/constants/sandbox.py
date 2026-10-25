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

# Home of the sandbox's unprivileged user on both backends: E2B's default "user"
# (see mount_juicefs.sh SANDBOX_USER) and the local image. Root disk, unlike /workspace.
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

# ── Local Docker-exec sandbox (ENV=selfhost without an E2B API key) ──
# See app/services/sandbox/local_sandbox.py for the implementation.

# Repository of the per-user local sandbox image, built from local_sandbox.Dockerfile
# on the host daemon; the tag is that file's content hash.
LOCAL_SANDBOX_IMAGE_REPOSITORY = "gaia-local-sandbox"

# Per-user containers are named ``<prefix><sanitized user_id>``.
LOCAL_SANDBOX_CONTAINER_PREFIX = "gaia-sandbox-"

# The self-host workspace volume (users/<uid>, skills/<uid>, _system). The API
# mounts it whole at JUICEFS_HOST_MOUNT_PATH; a local sandbox container mounts
# only its own user's subpaths of it. The compose file pins this exact name.
SELFHOST_WORKSPACE_VOLUME = "gaia-selfhost_workspace"

# The volume every local sandbox mounted whole before per-user isolation; only
# the one-shot legacy migration still reads it.

# Label recording the layout and image a sandbox was created with; an older one is replaced.
# v2: resource limits, dropped capabilities, isolated network.
# v3: built image, shared agents' home, host-gateway alias. v4: --init reaps zombies.
LOCAL_SANDBOX_LAYOUT_LABEL = "gaia.sandbox.layout"
LOCAL_SANDBOX_LAYOUT = "per-user-subpath-v4"

# Per-container ceilings, so one user's runaway build or fork bomb cannot starve
# the API and datastores sharing the host. Swap equals memory: no swap at all.
LOCAL_SANDBOX_MEMORY_LIMIT = "2g"
LOCAL_SANDBOX_MEMORY_SWAP_LIMIT = LOCAL_SANDBOX_MEMORY_LIMIT
LOCAL_SANDBOX_PIDS_LIMIT = 512
LOCAL_SANDBOX_CPUS = "2"

# Dedicated bridge for sandbox containers: internet egress (pip/npm installs)
# but no route to gaia_network's datastores, and inter-container traffic off so
# one user's sandbox cannot reach another's.
LOCAL_SANDBOX_NETWORK = "gaia-sandbox"
LOCAL_SANDBOX_NETWORK_ICC_OPTION = "com.docker.network.bridge.enable_icc=false"
# The host as sandbox containers see it, so a run's hooks reach GAIA through the
# proxy's published port (LOCAL_SANDBOX_LAB_EVENTS_CALLBACK_URL).
LOCAL_SANDBOX_HOST_GATEWAY = "host.docker.internal:host-gateway"

# Extra seconds the host waits past a command's in-container `timeout` before
# killing the docker exec client itself, covering daemon round-trip latency.
LOCAL_SANDBOX_EXEC_TIMEOUT_GRACE_SECONDS = 10

# Exit status of a command coreutils `timeout --signal=KILL` killed (128 + 9).
LOCAL_SANDBOX_KILLED_EXIT_CODE = 137


# Workspace mountpoint inside local sandbox containers. Must equal
# WORKSPACE_ROOT (app.agents.workspace.paths) — the tools address files under
# /workspace and expect the container to see them there.
LOCAL_SANDBOX_WORKSPACE_MOUNT = "/workspace"

# Upper bound on one ensure_started() cycle. Covers the first image build (a
# base pull plus an apt install, ~1 min cold) plus daemon latency; the API container itself talks to the
# host Docker daemon over its socket, so first-acquire can legitimately be slow.
LOCAL_SANDBOX_START_TIMEOUT_SECONDS = 300

# What every coding tool tells the user on a self-host instance that has neither
# an E2B key nor the opt-in local sandbox (docker-compose.sandbox.yml).
CODE_EXECUTION_DISABLED_MESSAGE = (
    "code execution is not enabled on this instance. The admin can enable it by "
    "running `gaia up --code-sandbox` on the server, or by saving an E2B API key "
    "in Settings."
)
